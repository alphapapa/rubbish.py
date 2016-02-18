#!/usr/bin/env python

# * Imports

import ConfigParser
import logging as log


# * Classes

class TrashBin(object):
    """Represents an XDG trash bin."""

    def __init__(self, path):
        self.path = path

        # Verify path is a trash bin
        if not self._verify():
            log.critical("Path does not appear to be a valid XDG trash bin: %s" % self.path)
            return False

    def _verify(self):
        """Return True if TrashBin appears to be a valid XDG trash bin."""

        pass

    def item_exists(name):
        """Return True if a file or directory _name_ exists in the trash
        bin.
        """

        pass


class TrashedPath(object):
    """Represents a trashed (or to-be-trashed) file or directory."""

    def __init__(self, path=None, trashinfo_file_path=None):
        self.date_trashed = None
        self.path = None
        self.trashed = False

        if path:
            self.path = path
        if trashinfo_file_path:
            self._parse_trashinfo_file(trashinfo_file_path)

    def _parse_trashinfo_file(self, trashinfo_file_path):
        """Parse .trashinfo file and populate object attributes."""

        trashinfo = ConfigParser.SafeConfigParser(allow_no_value=True)

        # Read file
        try:
            trashinfo.read(trashinfo_file_path)
        except Exception:
            log.exception("Unable to read trashinfo file: %s" % trashinfo_file_path)
            return False

        # Load section
        if trashinfo.has_section('Trash Info'):
            data = trashinfo.items('Trash Info')
        else:
            log.warning("trashinfo file appears invalid or empty: %s" % trashinfo_file_path)
            return False

        # Read and assign attributes
        if data.hasattr('Path'):
            self.path = data['Path']
        if data.hasattr('DeletionDate'):
            self.date_trashed = data['DeletionDate']

    def _write_trashinfo_file(self):
        """Write .trashinfo file for trashed path."""

        pass

    def restore(self, dest_path=None):
        """Restore a path from the trash to its original location.  If
        _dest_path_ is given, restore to there instead.
        """

        pass

    def trash(self):
        """Write .trashinfo file, then move the path to the trash."""

        # Rename if destination path already exists

        # os.path.basename behaves differently than the basename unix
        # util. Will have to compensate for this.

        # Write trashinfo file
        try:
            self._write_trashinfo_file()
        except:
            return False

        # Move path to trash
