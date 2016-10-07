#!/usr/bin/env python3

# * Imports

import logging as log
import re

from configparser import ConfigParser, ParsingError, NoSectionError, NoOptionError
from datetime import datetime
from pathlib import Path

# * Constants

TRASHINFO_SECTION_HEADER = 'Trash Info'
TRASHINFO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


# * Classes

class InvalidTrashBin(Exception):
    pass

class TrashBin(object):
    """Represents an XDG trash bin."""

    def __init__(self, path):
        self.path = Path(path)
        self.files_path = self.path / "files"
        self.info_path = self.path / "info"
        self.files = []

        # Verify path is a trash bin
        self._verify()

    def _verify(self):
        """Return True if TrashBin appears to be a valid XDG trash bin."""

        # TODO: Should we check write permission too?

        # Verify dirs exist
        if not (self.files_path.is_dir() and
                self.info_path.is_dir()):
            raise InvalidTrashBin("Path does not appear to be a valid XDG trash bin: %s", self.path)

    # def item_exists(self, name):
    #     """Return True if a file or directory _name_ exists in the trash bin.

    #     Checks both "Trash/files/_name_" and "Trash/info/_name_.trashinfo" paths.
    #     """

    #     if all(
    #     for test_path in [self.files_path / name,
    #                       self.info_path / "%s.trashinfo".format(name)]:
    #         if (test_path):
    #             return True

    #     return False

    def list_items(self):
        """List items in trash bin.

        Trashed directories are not descended into."""

        if not self.files:
            self._read_info_files()

        print(self.files)

    def _read_info_files(self):
        """Read .trashinfo files in bin and populate list of files."""

        for f in self.info_path.glob("*.trashinfo"):
            try:
                self.files.append(TrashedPath(info_file=f))
            except Exception:
                raise Exception("sigh")
            else:
                log.debug("Read info file: %s", f)

        log.debug("Read %s info files", len(self.files))

class TrashedPath(object):
    """Represents a trashed (or to-be-trashed) file or directory."""

    def __init__(self, bin=None, path=None, info_file=None):
        # TODO: Should I pass this in as an argument instead?
        self.bin = bin

        self.original_path = None
        self.trashed = False

        # TODO: Check FreeDesktop.org specs to see if timezone/UTC is specified.
        self.date_trashed = None  # datetime object in UTC

        if path:
            self.original_path = Path(path)
        if info_file:
            if isinstance(info_file, str):
                self.info_file = Path(info_file)
            elif isinstance(info_file, Path):
                self.info_file = info_file

            self._read_trashinfo_file()
            self.trashed_path = self.info_file.parent.parent / "files" / self.info_file.stem

    def _change_basename_if_necessary(self):
        """Rename self.basename if it already exists in the trash bin."""

        # TODO: Consider doing the suffix differently. If there were
        # some files named like "foo_100", a situation could arise in
        # which they failed to get trashed because of naming
        # conflicts.

        tries = 0
        while self.bin.item_exists(self.basename):
            log.debug("Path exists in trash: ", self.basename)

            if tries == 100:
                raise Exception("Tried 100 names.  That seems like too many.")

            # Get "_1"-like suffix
            match = re.search('^(.*)_([0-9]+)$', self.basename)
            if match:
                # Increment existing _number suffix
                name_without_suffix = match.group(0)
                number = int(match.group(1))
                number += 1
                self.basename = "%s_%s" % (name_without_suffix, number)
            else:
                # Add suffix
                self.basename = "%s_1" % self.basename

            log.debug("Trying new basename: ", self.basename)
            tries += 1

        log.debug("Renamed %s times", tries)

    def _read_trashinfo_file(self):
        """Read .trashinfo file and set object properties."""

        trashinfo = ConfigParser(interpolation=None)

        # Read file
        try:
            trashinfo.read(str(self.info_file))
            self.original_path = trashinfo.get(TRASHINFO_SECTION_HEADER, 'path')
            self.date_trashed = datetime.strptime(trashinfo.get(TRASHINFO_SECTION_HEADER, 'deletiondate'), TRASHINFO_DATE_FORMAT)
        except (ParsingError, NoSectionError, NoOptionError) as e:
            log.warning("trashinfo file appears invalid or empty: %s, %s", e.message, self.info_file)
            raise

        self.trashed = True

    def _write_trashinfo_file(self):
        """Write .trashinfo file for trashed path."""

        # Make trashinfo file path if it doesn't exist
        if not self.info_file:
            self.info_file = self.bin.info_path / "%s.trashinfo".format(self.path.name)

        # Verify trashinfo file doesn't exist
        if self.info_file.exists:
            raise Exception("Trashinfo file already exists: ", self.info_file)

        # Setup trashinfo
        trashinfo = SafeConfigParser()
        trashinfo.add_section(TRASHINFO_SECTION_HEADER)
        trashinfo.set(TRASHINFO_SECTION_HEADER, 'Path', self.path)
        trashinfo.set(TRASHINFO_SECTION_HEADER, 'DeletionDate', TRASHINFO_DATE_FORMAT % self.date_trashed)

        # Write the file
        try:
            with open(self.info_file, 'wb') as f:
                trashinfo.write(f)
        except:
            raise Exception("Unable to write trashinfo file: %s", self.info_file)

    def restore(self, dest_path=None):
        """Restore a path from the trash to its original location.  If
        _dest_path_ is given, restore to there instead.
        """

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

        pass

    def trash(self):
        """Write .trashinfo file, then move the path to the trash."""

        # Rename if necessary
        self._change_basename_if_necessary()

        # Set date_trashed
        self.date_trashed = datetime.utcnow()

        # Write trashinfo file
        self._write_trashinfo_file()

        # TODO: Move path to trash

        # TODO: Verify path doesn't already exist

        # Do I need to verify this again here?
        # _change_basename_if_necessary() should take care of this. Of
        # course, there's still a chance of a race condition, but if
        # os.path.rename overwrites, is it possible to avoid this?

if __name__ == "__main__":
    trash_bin = TrashBin()
