#!/usr/bin/env python3

# * Imports

import logging as log
import os
import shutil

from configparser import ConfigParser
from datetime import datetime
from pathlib import Path
from time import mktime

# ** Third-party

import click
import humanize
import parsedatetime

# * Constants

TRASHINFO_SECTION_HEADER = 'Trash Info'
TRASHINFO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# * Classes

class CaseConfigParser(ConfigParser):
    """Case-sensitive version of ConfigParser."""

    # This is necessary because some software that uses the trash bin
    # requires that the keys in the ini-style .trashinfo files be
    # capitalized in CamelCase.  This is not smart--has no one heard
    # of Postel anymore?!--but that's how it is.

    # See <http://stackoverflow.com/questions/1611799/preserve-case-in-configparser>

    def optionxform(self, optionstr):
        return optionstr

class TrashBin(object):
    """Represents an XDG trash bin."""

    def __init__(self, path=os.path.expanduser("~/.local/share/Trash")):
        self.path = Path(path)
        self.files_path = self.path / "files"
        self.info_path = self.path / "info"
        self.items = []

        # Verify path is a trash bin
        self._verify()

    def _verify(self):
        """Verify that trash bin appears to be a valid XDG trash bin.

        Considered valid if the "files" and "info" subdirectories exist."""

        # TODO: Should we check write permission too?

        # Verify dirs exist
        if not (self.files_path.is_dir() and
                self.info_path.is_dir()):
            raise Exception("Path does not appear to be a valid XDG trash bin: %s", self.path)

    def empty(self=None, size=False, trashed_before=None):
        """Delete items from trash bin.

        size: If true, return total size of files deleted.

        trashed_before: Either a datetime.datetime object or a string
                        parseable by parsedatetime.  Items trashed
                        before this will be deleted.
        """

        if not self:
            self = TrashBin()

        if not self.items:
            self._read_info_files()

        if not trashed_before:
            raise Exception("trashed_before is required right now.")

        # Convert relative date string to datetime object
        trashed_before = date_string_to_datetime(trashed_before)

        # FIXME: This seems to be inaccurate compared to du
        # TODO: Use shutil.disk_usage?
        total_size = 0
        for item in sorted(self.items, key=lambda i: i.date_trashed):

            # TODO: Since the items are sorted, we should break the
            # loop as soon as we encounter an item we aren't deleting.
            if item.date_trashed < trashed_before:
                try:
                    log.debug("Deleting item: %s (%s)", item.trashed_path, item.info_file)

                    if size:
                        # Save size for later recording
                        last_size = path_size(item.trashed_path)

                    # Actually delete file
                    if item.trashed_path.is_dir():
                        shutil.rmtree(str(item.trashed_path))
                    else:
                        item.trashed_path.unlink()

                    # TODO: If a "[Errno 2] No such file or directory"
                    # error happens because the trashed file isn't in
                    # the trash bin, we should, at least optionally,
                    # go ahead and delete the .trashinfo file.

                except Exception as e:
                    log.warning('Unable to delete item: %s: %s', item.trashed_path, e)
                else:
                    log.info("Deleted item originally at: %s", item.original_path)

                    # Log size
                    if size:
                        total_size += last_size

                    # Remove info file
                    try:
                        item.info_file.unlink()
                    except Exception as e:
                        log.warning("Unable to remove info file: %s: %s", item.info_file, e.message)
                    else:
                        log.debug("Deleted info file: %s", item.info_file)

        if size:
            return total_size

    def orphans(self):
        """Return list of trashed items which lack a .trashinfo file."""

        if not self.items:
            self._read_info_files()

        def trashed_path_in_info_files(path):
            # Return True if PATH is a trashed_path in this trash bin.
            for item in self.items:
                if item.trashed_path == path:
                    return True

        return [f for f in self.files_path.iterdir()
                if not trashed_path_in_info_files(f)]

    def item_exists(self, filename):
        """Return True if filename exists in trash bin's files/ subdirectory."""

        if Path(self.files_path / filename).exists():
            log.debug("Trashed path exists: %s", self.files_path / filename)

            return True

        elif Path(self.info_path / ("%s.trashinfo" % filename)).exists():
            log.debug("Info file exists: %s", self.info_path / ("%s.trashinfo" % filename))

            return True

        else:
            return False

    def _read_info_files(self):
        """Read .trashinfo files in bin and populate list of files."""

        for f in self.info_path.glob("*.trashinfo"):
            try:
                self.items.append(TrashedPath(bin=self, info_file=f))
            except OrphanTrashinfoFile:
                log.warning('.trashinfo file appears to be orphaned: %s', f)
            except Exception:
                # More info is printed with log.debug from TrashedPath._read_trashinfo_file
                log.warning('Unable to read info file: %s', f)
            else:
                log.debug("Read info file: %s", f)

        log.debug("Read %s info files", len(self.items))

class TrashedPath(object):
    """Represents a trashed (or to-be-trashed) file or directory."""

    def __init__(self, path=None, bin=None, info_file=None):
        self.bin = bin if bin else TrashBin()

        self.info_file = None
        self.original_path = None
        self.trashed = False
        self.trashed_path = None
        self.size = None

        # TODO: Check FreeDesktop.org specs to see if timezone/UTC is specified.
        self.date_trashed = None  # datetime object in UTC

        if path:
            self.original_path = Path(path)

            # Get absolute path
            if not self.original_path.is_absolute():
                # Prepend current directory
                self.original_path = os.getcwd() / self.original_path

        if info_file:
            # Probably already a trashed file
            if isinstance(info_file, str):
                self.info_file = Path(info_file)
            elif isinstance(info_file, Path):
                self.info_file = info_file

            try:
                self._read_trashinfo_file()
            except Exception as e:
                raise Exception('Unable to read .trashinfo file ("%s"): %s', e, self.info_file)

    def read_size(self):
        """Read and set size for item's size on disk."""

        try:
            self.size = path_size(self.trashed_path)
        except FileNotFoundError:
            log.warning("Trashed path not found: %s" % self.trashed_path)

    def _read_matching_info_file(self):
        """Find and read .trashinfo file for item's path."""

        # Save path for later
        path = self.original_path
        filename = path.name

        # FIXME: If a user accidentally trashes a .trashinfo file, the
        # resulting "foo.trashinfo.trashinfo" file may cause issues...

        # Find .trashinfo files matching name pattern
        info_files = list(self.bin.info_path.glob("%s.trashinfo" % filename))
        info_files.extend(list(self.bin.info_path.glob("%s_*.trashinfo" % filename)))

        # Check result
        if not info_files:
            log.critical("No trashinfo files found for path: %s", str(self.original_path))

            return False

        elif len(info_files) == 1:
            log.debug("Found one .trashinfo file matching filename")

            self.info_file = info_files[0]
            self._read_trashinfo_file()

            return True

        elif len(info_files) > 1:
            log.debug("Found multiple .trashinfo files found matching filename")

            # Find ones that match path
            matching_info_files = []

            for f in info_files:
                self.info_file = f
                self._read_trashinfo_file()  # Modifies self.original_path, etc.

                # Verify path
                if self.original_path == path:
                    matching_info_files.append(f)

            # Check result
            if len(matching_info_files) == 1:
                log.debug("Found matching info file: ", str(self.info_file))
            elif len(matching_info_files) > 1:
                raise Exception("Multiple matching info files: ", ", ".join([str(i.name) for i in matching_info_files]))
            else:
                raise Exception("No info files found matching path.")

    def _rename_if_necessary(self):
        """Rename self.trashed_path if a file by that name already exists in the trash bin."""

        if self.bin.item_exists(self.original_path.name):
            suffix = 1
            new_name = self.original_path.name + "_%s" % suffix

            while self.bin.item_exists(new_name):
                suffix += 1

                if suffix == 100:
                    raise Exception("Tried 100 suffixes for file: %s", self.original_path.name)

                new_name = self.original_path.name + "_%s" % suffix

            log.debug("Using new name with suffix \"%s\" for file: %s", new_name, self.original_path)

            self.trashed_path = self.trashed_path.with_name(new_name)

    def _read_trashinfo_file(self, check_orphan=False):
        """Read .trashinfo file and set item attributes."""

        parser = CaseConfigParser(interpolation=None)

        try:
            # Read file and load attributes
            parser.read(str(self.info_file))
            trashinfo = parser[TRASHINFO_SECTION_HEADER]

            self.original_path = Path(trashinfo['Path'])
            self.trashed_path = self.bin.files_path / self.info_file.stem
            self.date_trashed = datetime.strptime(trashinfo['DeletionDate'], TRASHINFO_DATE_FORMAT)

        except Exception as e:
            # TODO: Should this be an error or a warning?
            log.warning('.trashinfo file appears invalid or empty (%s): %s', e, self.info_file)
            raise e

        else:
            log.debug("Read .trashinfo file: %s", self.info_file)

            if check_orphan:
                if self.trashed_path.exists():
                    # Underlying file exists in trash
                    self.trashed = True

                    log.debug("Underlying file confirmed: %s", self.trashed_path)
                else:
                    # Orphan .trashinfo file
                    raise OrphanTrashinfoFile("Underlying file \"%s\" not found for: %s", self.trashed_path, self.info_file)

    def _remove_trashinfo_file(self):
        """Remove .trashinfo file from bin."""

        try:
            self.info_file.unlink()
        except Exception:
            log.exception("Can't remove .trashinfo file: %s", str(self.info_file))
        else:
            log.debug("Removed .trashinfo file: %s", str(self.info_file))

    def _write_trashinfo_file(self):
        """Write .trashinfo file for trashed path."""

        # TODO: Do I need to URL-escape the path?

        # Make trashinfo file path if it doesn't exist
        if not self.info_file:
            self.info_file = self.bin.info_path / "{}.trashinfo".format(self.trashed_path.name)

        # Verify trashinfo file doesn't exist
        if self.info_file.exists():
            raise Exception("Trashinfo file already exists: %s" % self.info_file)

        # Setup config parser
        parser = CaseConfigParser(interpolation=None)
        parser[TRASHINFO_SECTION_HEADER] = {}
        trashinfo = parser[TRASHINFO_SECTION_HEADER]
        trashinfo['Path'] = str(self.original_path)
        trashinfo['DeletionDate'] = self.date_trashed.strftime(TRASHINFO_DATE_FORMAT)

        # Write the file
        try:
            with self.info_file.open('w') as f:
                parser.write(f)
        except:
            log.error("Unable to write trashinfo file: %s" % self.info_file)
            raise
        else:
            log.debug("Wrote trashinfo file: %s", self.info_file)

    def delete(self):
        "Delete item from trash bin, including underlying file/directory and .trashinfo file."

        # Delete underlying file before deleting .trashinfo file, so
        # if it fails for some reason, the .trashinfo file will
        # remain, avoiding "orphan" files in the trash

        # Delete underlying file
        try:
            self.trashed_path.unlink()
        except Exception as e:
            log.error("Unable to delete file from trash bin: %s: %s", self.trashed_path, e)
        else:
            log.info("Deleted: %s", self.trashed_path)

        # Delete info file
        try:
            self.info_file.unlink()
        except Exception as e:
            log.error("Unable to delete file from trash bin: %s: %s", self.info_file, e)
        else:
            log.debug("Deleted: %s", self.info_file)

    def restore(self, dest=None):
        """Restore item to its original location or to DEST."""

        # Be careful not to overwrite existing files when using
        # os.path.rename! shutil.move might be useful, but it's
        # probably not the right solution either, because I don't want
        # to move a directory into a directory. e.g. If
        # /home/user/foo/bar is trashed, and then the user creates
        # that directory again, and then tries to restore it,
        # ~/foo/bar already exists, so shutil.move would put it in
        # ~/foo/bar/bar, which is not desired. But os.path.rename
        # would overwrite ~/foo/bar with the trashed bar, which could
        # delete an entire subdirectory tree, which is dangerous. I
        # don't know why Python doesn't seem to have some kind of
        # atomic, safe move/rename.

        # Seems like the best way to do it is to use os.link to create
        # a new hard link to the restored destination, then if it
        # succeeds, unlink the one in the trash

        # NOTE: This needs to correctly handle cases where the restore
        # would be to a path on a different filesystem, and cases
        # where the parent directory to restore to doesn't exist.

        # NOTE: I guess it probably isn't worth the complexity of
        # handling cross-filesystem restores and special casing it.
        # Might as well just move it and accept the minor risk of a
        # race overwriting an existing file.  On the other hand, we
        # could make a new hard link on the destination filesystem,
        # then copy to a temp file, then move it to overwrite the new
        # hard link, and then delete the file from the trash.  This is
        # probably the best way to do it.  It only adds a little
        # complexity to the cross-filesystem restore.

        # NOTE: There needs to be a higher-level UI to select the
        # items to restore.

        path_given = self.original_path

        # Read .trashinfo file for path
        if not self._read_matching_info_file():
            return False

        # Verify path matches given path
        if not self.original_path == path_given:
            log.critical("Path to restore (\"%s\")differs from original path in matching info file (\"%s\")",
                         path_given, self.original_path)

            return False

        # Set destination
        if dest:
            target_path = Path(dest) / self.original_path.name
        else:
            target_path = self.original_path

        # Ensure destination doesn't already exist
        if target_path.exists():
            log.critical("Can't restore because path already exists: %s" % str(target_path))

            return False

        # Move path back
        try:
            shutil.move(self.trashed_path.as_posix(), target_path.as_posix())
        except Exception as e:
            log.critical("Can't restore to path: %s: %s", target_path, e.message)

            return False
        else:
            # Restore complete
            log.info("Restored to path: %s", str(target_path))

            # Remove .trashinfo file
            self._remove_trashinfo_file()

    def trash(self):
        """Trash item in trash bin.

        Writes .trashinfo file, then moves path to trash bin."""

        # Write .trashinfo file first, so if it fails, we don't trash
        # the file, avoiding "orphaned" files in the bin.

        # Set trashed path (is this the best place to do this?)
        self.trashed_path = self.bin.files_path / self.original_path.name

        log.debug('Preparing to trash "%s" as "%s"', self.original_path, self.trashed_path)

        # Rename if necessary
        self._rename_if_necessary()

        # Set date_trashed
        self.date_trashed = datetime.utcnow()

        # Write trashinfo file
        self._write_trashinfo_file()

        # There seems to be no way to rename a path in Python without
        # potentially overwriting an existing path, so although we
        # change the basename if necessary above, there's still a
        # potential race condition that could cause an existing item
        # in the bin to be overwritten.

        # Actually, it might be possible to make a new hard link to
        # the file inside the trash bin, then unlink the original.
        # But that obviously won't work across filesystems, so maybe
        # it's not worth it.

        # Move path to trash
        try:
            # FIXME: Would Path.rename() suffice here, or does that not work across filesystems?
            shutil.move(self.original_path.as_posix(), self.trashed_path.as_posix())
        except Exception as e:
            log.error('Unable to move item "%s" to trashed path "%s": %s', self.original_path, self.trashed_path, e)

            # FIXME: Remove trashinfo file if trashing fails

            return False
        else:
            log.info('Trashed "%s" as: "%s"', self.original_path, self.trashed_path)

# ** Exceptions

class NoTrashinfoFilesFoundForPath(Exception):
    pass

class OrphanTrashinfoFile(Exception):
    pass

# * Functions

def date_string_to_datetime(s):
    "Convert date string to a datetime object using parsedatetime.Calendar()."

    # It's a shame that such a great library like parsedatetime
    # didn't go the extra inch and provide a decent API to get a
    # datetime object out of it.
    return datetime.fromtimestamp(mktime(parsedatetime.Calendar().parse(s)[0]))

def delete_paths(paths):
    """Delete PATHS and return total size of files deleted."""
    # Used for deleting orphaned trash files.

    total_size = 0
    for path in paths:
        try:
            log.debug("Deleting path: %s", path)

            # Save size for later recording
            last_size = path_size(path)

            # Actually delete file
            if path.is_dir():
                shutil.rmtree(str(path))
            else:
                path.unlink()
        except Exception as e:
             log.warning('Unable to delete item: %s: %s', path, e)
        else:
            log.info("Deleted path: %s", path)

            # Record size
            total_size += last_size

    return total_size

def format_size(size):
    "Return SIZE formatted for output."

    return humanize.naturalsize(size, gnu=True)

def path_size(path):
    "Return size of PATH (following symlinks) in bytes."

    size = 0
    if path.is_dir():
        for p in path.iterdir():
            size += path_size(p)
    else:
        # Use lstat in case path is a symlink.
        size += path.lstat().st_size

    return size

# * Setup Click

@click.group()
@click.option('-v', '--verbose', count=True)
def cli(verbose):

    # Setup logging
    if verbose >= 2:
        LOG_LEVEL = log.DEBUG
    elif verbose == 1:
        LOG_LEVEL = log.INFO
    else:
        LOG_LEVEL = log.WARNING

    log.basicConfig(level=LOG_LEVEL, format="%(levelname)s: %(message)s")

# * Commands

# ** empty

@click.command()
@click.option("--size", is_flag=True, help="Show total size of deleted files")
@click.option('--trashed-before', type=str,
                 help="Empty items trashed before this date. Date may be given in many formats, "
                 "including natural language like \"1 month ago\".")
def empty(bin=TrashBin(), size=False, trashed_before=None):
    """Empty files from trash bin."""

    total_size = bin.empty(trashed_before=trashed_before, size=size)
    if size and total_size:
        # FIXME: This should be logged to STDERR, probably.
        print("Total size of files emptied:", format_size(total_size))

# ** expire

# TODO: Make an "expire" command that would do what "empty --trashed-before" does.  Much clearer.

# ** orphans

@click.command()
@click.option("--empty", is_flag=True, help="Empty orphans from bin")
@click.option("--size", is_flag=True, help="Show total size of orphans")
def orphans(bin=TrashBin(), empty=False, size=False):
    """List or empty orphaned trash files.

    Orphans are files in the trash bin without a corresponding .trashinfo file."""

    if empty:
        # Empty orphans from bin.
        total_size = delete_paths(bin.orphans())
        print("Total size of orphans emptied:", format_size(total_size))
    else:
        # Just list orphans.
        orphans = bin.orphans()

        if size:
            total_size = 0
            for orphan in orphans:
                orphan_size = path_size(orphan)
                total_size += orphan_size
                print("%s (%s)" % (str(orphan), format_size(orphan_size)))
            print("Total size:", format_size(total_size))
        else:
            for orphan in orphans:
                print(str(orphan))

# ** list

@click.command("list")
@click.option("--size", is_flag=True, help="Show total size of trashed files")
@click.option('--trashed-before', type=str,
                 help="List items trashed before this date. Date may be given in many formats, "
                 "including natural language like \"1 month ago\".")
def list_items(bin=TrashBin(), size=False, trashed_before=None):
    """Print list of items in trash bin."""

    if not bin.items:
        bin._read_info_files()

    if trashed_before:
        # Print items trashed before a certain time.

        # Convert relative date string to datetime object.
        trashed_before = date_string_to_datetime(trashed_before)

        items = [f for f in bin.items
                 if f.date_trashed < trashed_before]
    else:
        # Print all items
        items = bin.items

    if size:
        # Print items with sizes.
        for item in items:
            item.read_size()
        items = sorted(items, key=lambda i: i.size if i.size else 0)

        total_size = 0
        for item in items:
            if item.size:
                human_size = format_size(item.size)
                total_size += item.size
            else:
                human_size = None
            print("{} ({}): {}".format(item.date_trashed, human_size, item.original_path))
        print("Total size:", format_size(total_size))
        print("Trashed-On HH:MM:SS (Size): /Original/Path")
    else:
        # Print items without size.
        for item in sorted(bin.items, key=lambda i: i.date_trashed):
            print("{}: {}".format(item.date_trashed, item.original_path))
        print("Trashed-On HH:MM:SS: /Original/Path")

# ** restore

@click.command()
@click.option("--to", type=click.Path(exists=True),
              help="Restore to this directory instead of original location")
@click.argument('paths', type=click.Path(exists=False), nargs=-1)
def restore(paths, to=None, bin=None):
    """Restore paths from trash bin to original location, or to directory TO."""

    # Instantiate bin once
    bin = TrashBin()

    for path in paths:
        TrashedPath(path, bin=bin).restore(dest=to)

# ** trash

@click.command()
@click.argument('paths', type=click.Path(exists=True), nargs=-1)
def trash(paths, bin=None):
    """Move paths to trash bin."""

    # Instantiate bin once
    bin = TrashBin()

    for path in paths:
        TrashedPath(path, bin=bin).trash()

# * Run cli

if __name__ == "__main__":
    cli.add_command(empty)
    cli.add_command(list_items)
    cli.add_command(orphans)
    cli.add_command(restore)
    cli.add_command(trash)

    cli()
