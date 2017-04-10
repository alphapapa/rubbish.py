#!/usr/bin/env python3

# * Imports

import logging as log
import re
import os
import shutil

from configparser import ConfigParser, ParsingError, NoSectionError, NoOptionError
from datetime import datetime
from pathlib import Path
from time import mktime

import click
import hurry.filesize
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

    def empty(self=None, trashed_before=None):
        """Delete items from trash bin.

        trashed_before: Either a datetime.datetime object or a string
                        parseable by parsedatetime.  Items trashed
                        before this will be deleted.
        """

        print(trashed_before)

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
            if item.date_trashed < trashed_before:
                try:
                    total_size += item.trashed_path.lstat().st_size # Use lstat in case it's a symlink
                except Exception as e:
                    log.warning('Unable to stat file: %s: %s', item.trashed_path, e)
                else:
                    log.debug("Would delete: %s: %s", item.date_trashed, item.original_path)

        print("Total size:", hurry.filesize.size(total_size, system=hurry.filesize.alternative))

    def list_items(self, trashed_before=None):
        """List items in trash bin.

        Trashed directories are not descended into."""

        if not self.items:
            self._read_info_files()

        if trashed_before:
            # Convert relative date string to datetime object
            trashed_before = date_string_to_datetime(trashed_before)

            for f in sorted(self.items, key=lambda i: i.date_trashed):
                if f.date_trashed < trashed_before:
                    print("{}: {}".format(f.date_trashed, f.original_path))
        else:
            # Print all items
            print("\n".join(str(i.original_path) for i in sorted(self.items, key=lambda i: i.original_path)))

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

        # TODO: Check FreeDesktop.org specs to see if timezone/UTC is specified.
        self.date_trashed = None  # datetime object in UTC

        if path:
            self.original_path = Path(path)

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
            else:
                log.debug("Read .trashinfo file: %s", self.info_file)

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
            log.debug("Deleted: %s", self.trashed_path)

        # Delete info file
        try:
            self.info_file.unlink()
        except Exception as e:
            log.error("Unable to delete file from trash bin: %s: %s", self.info_file, e)
        else:
            log.debug("Deleted: %s", self.info_file)

    def restore(self, dest_path=None):
        """Restore item to its original location.

        If _dest_path_ is given, restore to there instead."""

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

        pass

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
            shutil.move(self.original_path, self.trashed_path)
        except Exception as e:
            log.error('Unable to move item "%s" to trashed path "%s": %s', self.original_path, self.trashed_path, e)

            # FIXME: Remove trashinfo file if trashing fails

            return False
        else:
            log.debug('Trashed "%s" as: "%s"', self.original_path, self.trashed_path)

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

# * Setup Click

@click.group()
@click.option('-v', '--verbose', count=True)
def cli(verbose):

    # Setup logging
    if verbose >= 2:
        LOG_LEVEL = log.DEBUG
    elif verbose == 1:
        LOG_LEVEL = log.WARNING
    else:
        LOG_LEVEL = log.ERROR

    log.basicConfig(level=LOG_LEVEL, format="%(levelname)s: %(message)s")

# * Commands

# ** empty

@click.command()
@click.option('--trashed-before', type=str,
                 help="Empty items trashed before this date. Date may be given in many formats, "
                 "including natural language like \"1 month ago\".")
def empty(bin=TrashBin(), trashed_before=None):
    bin.empty(trashed_before=trashed_before)

# ** show

@click.command()
def show(bin=TrashBin()):
    bin.list_items()

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
    cli.add_command(show)
    cli.add_command(trash)

    cli()
