import contextlib
import os

from scale_build.utils.paths import PKG_DIR


class BuildCleanMixin:

    def clean_previous_packages(self):
        if not os.path.exists(self.pkglist_hash_file_path):
            # Nothing to do
            return False

        with open(self.pkglist_hash_file_path, 'r') as f:
            to_remove = [p for p in map(str.strip, f.read().split()) if p]

        os.unlink(self.pkglist_hash_file_path)
        if not to_remove:
            return False

        for name in to_remove:
            self.logger.debug(f'Removing previously built packages for {self.name}: {name}')
            with contextlib.suppress(OSError, FileNotFoundError):
                os.unlink(os.path.join(PKG_DIR, name))
        return True
