#!/usr/bin/env python

# * Imports

import ConfigParser
import logging as log
import os
import re


# * Constants

SECTION = 'Trash Info'


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

        self.basename = None
        self.date_trashed = None
        self.original_path = None
        self.trashed = False

        if path:
            self.original_path = path
            self.basename = self._basename(self.original_path)
        if trashinfo_file_path:
            self._read_trashinfo_file(trashinfo_file_path)

    def _basename(self, path):
        """Return basename of _path_.

        A wrapper for os.path.basename() that strips the slash off the
        end, making it behave like the "basename" command.
        """

        return os.path.basename(path.rstrip('/'))

    def _rename_basename_if_necessary(self):
        """Rename self.basename if it already exists in the trash bin."""

        tries = 0
        while self.trash_bin.item_exists(self.basename):
            log.debug("Path exists in trash: ", test_path)

            if tries == 100:
                log.critical("Tried 100 names.  That seems like too many.")
                return False

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

        log.debug("Done renaming.")

    def _read_trashinfo_file(self, trashinfo_file_path):
        """Read .trashinfo file and populate object attributes."""

        trashinfo = ConfigParser.SafeConfigParser(allow_no_value=True)

        # Read file
        try:
            trashinfo.read(trashinfo_file_path)
        except:
            log.exception("Unable to read trashinfo file: %s", trashinfo_file_path)
            return False

        self.basename = os.path.basename(trashinfo_file_path)

        # Load section
        if trashinfo.has_section(SECTION):
            data = trashinfo.items(SECTION)
        else:
            log.warning("trashinfo file appears invalid or empty: %s", trashinfo_file_path)
            return False

        # Read and assign attributes
        if data.hasattr('Path'):
            self.original_path = data['Path']
        else:
            log.warning("trashinfo file has no Path attribute: %s", trashinfo_file_path)

        if data.hasattr('DeletionDate'):
            self.date_trashed = data['DeletionDate']
        else:
            log.warning("trashinfo file has no DeletionDate attribute: %s", trashinfo_file_path)

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
        trashinfo.add_section(SECTION)
        trashinfo.set(SECTION, 'Path', self.path)
        trashinfo.set(SECTION, 'DeletionDate', self.date_trashed)

        # Write the file
        try:
            with open(os.path.join(self.trash_bin.info_path, self.filename), 'wb') as f:
                trashinfo.write(f)
        except:
            log.exception("Unable to write trashinfo file: %s", self.trashinfo_file_path)
            return False

    def restore(self, dest_path=None):
        """Restore a path from the trash to its original location.  If
        _dest_path_ is given, restore to there instead.
        """

        # Be careful not to overwrite existing files when using
        # os.path.rename!

        pass

    def trash(self):
        """Write .trashinfo file, then move the path to the trash."""

        # Rename if necessary
        if not self._rename_basename_if_necessary():
            return False

        # TODO: Set date_trashed

        # Write trashinfo file
        if not self._write_trashinfo_file():
            return False

        # TODO: Move path to trash

trash_bin = TrashBin()
