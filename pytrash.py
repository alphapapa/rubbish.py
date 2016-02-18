#!/usr/bin/env python

# * Imports

import ConfigParser
import logging as log
import os


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
            log.critical("Path does not appear to be a valid XDG trash bin: %s" % self.path)
            return False

    def _verify(self):
        """Return True if TrashBin appears to be a valid XDG trash bin."""

        # TODO: Should we check write permission too?

        # Verify dirs exist
        if not (os.path.exists(self.files_path) and
                os.path.exists(self.info_path)):
                return False

    def item_exists(name):
        """Return True if a file or directory _name_ exists in the trash
        bin.
        """

        # Should this check just the actual file in "files/", or also
        # the associated trashinfo file in "info/"?

        pass


class TrashedPath(object):
    """Represents a trashed (or to-be-trashed) file or directory."""

    def __init__(self, path=None, trashinfo_file_path=None):
        self.date_trashed = None
        self.filename = None
        self.original_path = None
        self.trashed = False

        global trash_bin
        self.trash_bin = trash_bin

        if path:
            self.original_path = path
        if trashinfo_file_path:
            self._read_trashinfo_file(trashinfo_file_path)

    def _read_trashinfo_file(self, trashinfo_file_path):
        """Read .trashinfo file and populate object attributes."""

        trashinfo = ConfigParser.SafeConfigParser(allow_no_value=True)

        # Read file
        try:
            trashinfo.read(trashinfo_file_path)
        except:
            log.exception("Unable to read trashinfo file: %s" % trashinfo_file_path)
            return False

        # Load section
        if trashinfo.has_section(SECTION):
            data = trashinfo.items(SECTION)
        else:
            log.warning("trashinfo file appears invalid or empty: %s" % trashinfo_file_path)
            return False

        # Read and assign attributes
        if data.hasattr('Path'):
            self.original_path = data['Path']
        else:
            log.warning("trashinfo file has no Path attribute: %s" % trashinfo_file_path)

        if data.hasattr('DeletionDate'):
            self.date_trashed = data['DeletionDate']
        else:
            log.warning("trashinfo file has no DeletionDate attribute: %s" % trashinfo_file_path)

    def _write_trashinfo_file(self):
        """Write .trashinfo file for trashed path."""

        # Setup trashinfo
        trashinfo = ConfigParser.SafeConfigParser()
        trashinfo.add_section(SECTION)
        trashinfo.set(SECTION, 'Path', self.path)
        trashinfo.set(SECTION, 'DeletionDate', self.date_trashed)

        # Write the file
        try:
            with open(os.path.join(self.trash_bin.info_path, self.filename),
                      'wb') as f:
                trashinfo.write(f)
        except:
            log.exception("Unable to write trashinfo file: %s" % self.trashinfo_file_path)
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

        # Rename if destination path already exists

        # os.path.basename behaves differently than the basename unix
        # util. Will have to compensate for this.

        # Set date_trashed

        # Write trashinfo file
        try:
            self._write_trashinfo_file()
        except:
            return False

        # Move path to trash

trash_bin = TrashBin()
