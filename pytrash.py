#!/usr/bin/env python

# * Imports

import ConfigParser
import logging as log
import os
import re

from datetime import datetime


# * Constants

TRASHINFO_SECTION_HEADER = 'Trash Info'
TRASHINFO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


# * Classes


class TrashBin(object):
    """Represents an XDG trash bin."""

    def __init__(self, path):
        self.path = path
        self.files_path = os.path.join(self.path, 'files')
        self.info_path = os.path.join(self.path, 'info')

        # Verify path is a trash bin
        if not self._verify():
            log.critical("Path does not appear to be a valid XDG trash bin: %s", self.path)
            return False

    def _verify(self):
        """Return True if TrashBin appears to be a valid XDG trash bin."""

        # TODO: Should we check write permission too?

        # Verify dirs exist
        if not (os.path.exists(self.files_path) and
                os.path.exists(self.info_path)):
                return False

    def item_exists(self, name):
        """Return True if a file or directory _name_ exists in the trash bin.

        Checks both "Trash/files/_name_" and "Trash/info/_name_.trashinfo" paths.
        """

        for test_path in [os.path.join(self.files_path, name),
                          os.path.join(self.info_path, "%s.trashinfo" % name)]:
            if os.path.exists(test_path):
                return True

        return False


class TrashedPath(object):
    """Represents a trashed (or to-be-trashed) file or directory."""

    def __init__(self, path=None, trashinfo_file_path=None):
        # TODO: Should I pass this in as an argument instead?
        global trash_bin
        self.trash_bin = trash_bin

        self.original_path = None
        self.trashed = False

        # Name in trash bin (possibly with suffix for uniqueness)
        self.basename = None

        # TODO: Check FreeDesktop.org specs to see if timezone/UTC is specified.
        self.date_trashed = None  # datetime object in UTC

        if path:
            self.original_path = path
            self.basename = self._basename(path)
        if trashinfo_file_path:
            self.trashinfo_file_path = trashinfo_file_path
            self._read_trashinfo_file()

    def _basename(self, path):
        """Return basename of _path_.

        A wrapper for os.path.basename() that strips the slash off the
        end, making it behave like the "basename" command.
        """

        return os.path.basename(path.rstrip('/'))

    def _change_basename_if_necessary(self):
        """Rename self.basename if it already exists in the trash bin."""

        # TODO: Consider doing the suffix differently. If there were
        # some files named like "foo_100", a situation could arise in
        # which they failed to get trashed because of naming
        # conflicts.

        tries = 0
        while self.trash_bin.item_exists(self.basename):
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

        trashinfo = ConfigParser.SafeConfigParser(allow_no_value=True)

        # Read file
        try:
            trashinfo.read(self.trashinfo_file_path)
        except:
            log.critical("Unable to read trashinfo file: %s", self.trashinfo_file_path)
            raise

        # Set basename from trashinfo_file_path
        self.basename = os.path.basename(self.trashinfo_file_path)

        # Load section
        if trashinfo.has_section(TRASHINFO_SECTION_HEADER):
            data = trashinfo.items(TRASHINFO_SECTION_HEADER)
        else:
            log.critical("trashinfo file appears invalid or empty: %s", self.trashinfo_file_path)
            raise

        # Read and assign attributes
        if 'Path' in data:
            self.original_path = data['Path']
        else:
            # The Path is missing, so the trashinfo file is useless
            log.critical("trashinfo file has no Path attribute: %s", self.trashinfo_file_path)
            raise

        if 'DeletionDate' in data:
            try:
                self.date_trashed = datetime.strptime(data['DeletionDate'], TRASHINFO_DATE_FORMAT)
            except ValueError:
                log.critical("Unable to parse date (%s) from trashinfo file: %s", data['DeletionDate'], self.trashinfo_file_path)
                raise
        else:
            log.warning("trashinfo file has no DeletionDate attribute: %s", self.trashinfo_file_path)

    def _write_trashinfo_file(self):
        """Write .trashinfo file for trashed path."""

        # Make trashinfo file path if it doesn't exist
        if not self.trashinfo_file_path:
            self.trashinfo_file_path = os.path.join(self.trash_bin.info_path, "%s.trashinfo" % self.basename)
            log.debug("Set trashinfo file path: ", self.trashinfo_file_path)

        # Verify trashinfo file doesn't exist
        if os.path.exists(self.trashinfo_file_path):
            log.warning("Trashinfo file already exists: ", self.trashinfo_file_path)
            return False

        # Setup trashinfo
        trashinfo = ConfigParser.SafeConfigParser()
        trashinfo.add_section(TRASHINFO_SECTION_HEADER)
        trashinfo.set(TRASHINFO_SECTION_HEADER, 'Path', self.path)
        trashinfo.set(TRASHINFO_SECTION_HEADER, 'DeletionDate', TRASHINFO_DATE_FORMAT % self.date_trashed)

        # Write the file
        try:
            with open(os.path.join(self.trash_bin.info_path, self.filename), 'wb') as f:
                trashinfo.write(f)
        except:
            log.critical("Unable to write trashinfo file: %s", self.trashinfo_file_path)
            raise

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

trash_bin = TrashBin()
