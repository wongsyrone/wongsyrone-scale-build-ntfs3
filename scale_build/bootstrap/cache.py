import os
import shutil

from scale_build.utils.paths import CACHE_DIR
from scale_build.utils.reference_files import compare_reference_files
from scale_build.utils.run import run

from .hash import get_all_repo_hash


class CacheMixin:

    @property
    def cache_filename(self):
        raise NotImplementedError

    @property
    def cache_file_path(self):
        return os.path.join(CACHE_DIR, self.cache_filename)

    @property
    def cache_exists(self):
        return all(
            os.path.exists(p) for p in (self.cache_file_path, self.saved_packages_file_path, self.cache_hash_file_path)
        )

    def remove_cache(self):
        for path in filter(
            lambda p: os.path.exists(p),
            (self.cache_file_path, self.saved_packages_file_path, self.cache_hash_file_path)
        ):
            os.unlink(path)

    def get_mirror_cache(self):
        if self.cache_exists:
            with open(self.cache_hash_file_path, 'r') as f:
                return f.read().strip()

    def save_build_cache(self, installed_packages):
        self.logger.debug('Caching CHROOT_BASEDIR for future runs...')
        run(['mksquashfs', self.chroot_basedir, self.cache_file_path])
        self.update_saved_packages_list(installed_packages)
        self.update_mirror_cache()

    @property
    def mirror_cache_intact(self):
        from .bootstrapdir import PackageBootstrapDir, RootfsBootstrapDir, CdromBootstrapDirectory
        intact = True
        if not self.cache_exists:
            # No hash file? Lets remove to be safe
            intact = False
            self.logger.debug('Cache does not exist')

        elif get_all_repo_hash() != self.get_mirror_cache():
            self.logger.debug('Upstream repo changed! Removing squashfs cache to re-create.')
            intact = False

        if isinstance(self, PackageBootstrapDir):
            tmp_name = "PackageBootstrapDir"
        elif isinstance(self, RootfsBootstrapDir):
            tmp_name = "RootfsBootstrapDir"
        elif isinstance(self, CdromBootstrapDirectory):
            tmp_name = "CdromBootstrapDirectory"
        else:
            tmp_name = None

        if intact:
            self.restore_cache(self.chroot_basedir)
            for reference_file, diff in compare_reference_files(
                cut_nonexistent_user_group_membership=True,
                default_homedir='/var/empty'
            ):
                if diff:
                    intact = False
                    self.logger.debug(
                        'Reference file %r changed, removing squashfs cache to re-create with it '
                        'having following diff:\n%s',
                        reference_file, '\n'.join(diff)
                    )
                    break

            # Remove the temporary restored cached directory
            shutil.rmtree(self.chroot_basedir, ignore_errors=True)

        if not intact:
            self.remove_cache()
            if tmp_name is not None:
                with open(f'/tmp/{tmp_name}', 'w') as f:
                    f.write(f"{(1 if intact else 0)}")

        return intact

    @property
    def installed_packages_in_cache_changed(self):
        return self.installed_packages_in_cache != self.get_packages()

    def restore_cache(self, chroot_basedir):
        run(['unsquashfs', '-f', '-d', chroot_basedir, self.cache_file_path])
