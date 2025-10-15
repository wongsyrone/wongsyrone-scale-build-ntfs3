import logging
import os
import shutil
import contextlib

from scale_build.config import (
    BRANCH_OVERRIDES, IDENTITY_FILE_PATH_OVERRIDE_SUFFIX, PACKAGE_IDENTITY_FILE_PATH_OVERRIDES,
    TRUENAS_BRANCH_OVERRIDE, TRY_BRANCH_OVERRIDE,
)
from scale_build.exceptions import CallError
from scale_build.utils.git_utils import (
    branch_checked_out_locally, branch_exists_in_repository, create_branch,
    retrieve_git_remote_and_sha, retrieve_git_branch, update_git_manifest
)
from scale_build.utils.logger import LoggingContext
from scale_build.utils.manifest import get_manifest, SSH_SOURCE_REGEX
from scale_build.utils.paths import GIT_LOG_DIR_NAME, GIT_LOG_DIR
from scale_build.utils.run import run

logger = logging.getLogger(__name__)


class GitPackageMixin:

    def branch_out(self, new_branch_name, base_branch_override=None):
        create_branch(self.source_path, base_branch_override or self.branch, new_branch_name)

    def branch_exists_in_remote(self, branch):
        return branch_exists_in_repository(self.origin, branch)

    def branch_checked_out_locally(self, branch):
        return branch_checked_out_locally(self.source_path, branch)

    def retrieve_current_remote_origin_and_sha(self):
        if self.exists:
            return retrieve_git_remote_and_sha(self.source_path)
        else:
            return {'url': None, 'sha': None}

    def update_git_manifest(self):
        info = self.retrieve_current_remote_origin_and_sha()
        update_git_manifest(info['url'], info['sha'])

    @property
    def git_log_file(self):
        return os.path.join(GIT_LOG_DIR_NAME, self.name)

    @property
    def git_log_file_path(self):
        return os.path.join(GIT_LOG_DIR, f'{self.name}.log')

    def checkout(self, branch_override=None, retries=3):
        self.validate_checkout()

        origin_url = self.retrieve_current_remote_origin_and_sha()['url']
        branch = branch_override or self.branch
        update = (branch == self.existing_branch) and self.origin == origin_url
        if update:
            cmds = (
                ['-C', self.source_path, 'fetch', 'origin'],
                ['-C', self.source_path, 'checkout', branch],
                ['-C', self.source_path, 'reset', '--hard', f'origin/{branch}'],
            )
        else:
            cmds = (
                ['clone', '--recurse',
                 '--depth', '1', '--single-branch', '--branch', branch,
                 self.origin, self.source_path],
                ['-C', self.source_path, 'checkout', branch],
            )

        # We're doing retries here because at the time of writing this the iX network
        # is having issues with an external hop through the routing of the interwebz
        # getting to github.com. They've found a particular hop is dropping significant
        # amounts of packets (~75%+). This is happening network wide so we've got the
        # retries.
        # NOTE: when the issue is fixed, we could remove this retry logic
        _min = 3
        _max = 10
        if retries < _min or retries > _max:
            raise RuntimeError(f'The number of retries must be between {_min!r} and {_max!r}')

        for i in range(1, retries + 1):
            if i == 1:
                log = 'Updating git repo' if update else 'Checking out git repo'
                logger_method = logger.debug
                open_mode = 'w'
            else:
                log = 'Retrying to update git repo' if update else 'Retrying to checkout git repo'
                logger_method = logger.warning
                open_mode = 'a'

            log += f' {self.name!r} (using branch {branch!r}) ({self.git_log_file_path})'
            logger_method(log)

            if not update:
                # if we're not updating then we need to remove the existing
                # git directory (if it exists) before trying to checkout
                with contextlib.suppress(FileNotFoundError):
                    shutil.rmtree(self.source_path)

            failed = False
            with LoggingContext(self.git_log_file, open_mode):
                if open_mode == 'a':
                    logger.warning(f'\n\n #####Attempt {i}##### \n\n')

                for cmd in map(lambda c: self.git_args + c, cmds):
                    cp = run(cmd, check=False)
                    if cp.returncode:
                        failed = (f'{" ".join(cmd)}', f'{cp.stdout}', f'{cp.returncode}')
                        break

            if failed:
                err = f'Failed cmd {failed[0]!r} with error {failed[1]!r} with returncode {failed[2]!r}.'
                err += f' Check {self.git_log_file!r} for details.'
                if i == retries:
                    raise CallError(err)
                else:
                    logger.warning(err)
                    continue
            else:
                break

        self.update_git_manifest()
        log = 'Checkout ' if not update else 'Updating '
        logger.info(log + 'of git repo %r (using branch %r) complete', self.name, branch)

    @property
    def git_args(self):
        if self.ssh_based_source:
            return [
                'git', '-c',
                f'core.sshCommand=ssh -i {self.get_identity_file_path} -o StrictHostKeyChecking=\'accept-new\''
            ]
        else:
            return ['git']

    @property
    def get_identity_file_path(self):
        # We need to use absolute path as git changes it's working directory with -C
        path = (PACKAGE_IDENTITY_FILE_PATH_OVERRIDES.get(self.name) or
                self.identity_file_path or
                get_manifest()['identity_file_path_default'])
        return os.path.abspath(os.path.expanduser(path)) if path else None

    @property
    def ssh_based_source(self):
        return bool(SSH_SOURCE_REGEX.findall(self.origin))

    def validate_checkout(self):
        if not self.ssh_based_source:
            return

        if not self.get_identity_file_path:
            raise CallError(
                f'Identity file path must be specified in order to checkout {self.name!r}. It can be done either as '
                'specifying "identity_file_path" attribute in manifest or providing '
                f'"{self.name}{IDENTITY_FILE_PATH_OVERRIDE_SUFFIX}" env variable specifying path of the file.'
            )

        if not os.path.exists(self.get_identity_file_path):
            raise CallError(f'{self.get_identity_file_path!r} identity file path does not exist')

        if oct(os.stat(self.get_identity_file_path).st_mode & 0o777) != '0o600':
            raise CallError(f'{self.get_identity_file_path!r} identity file path should have 0o600 permissions')

    @property
    def existing_branch(self):
        if not self.exists:
            return None
        return retrieve_git_branch(self.source_path)

    def get_branch_override(self):
        # We prioritise TRUENAS_BRANCH_OVERRIDE over any individual branch override
        # keeping in line with the behavior we used to have before
        gh_override = TRUENAS_BRANCH_OVERRIDE or BRANCH_OVERRIDES.get(self.name)

        # TRY_BRANCH_OVERRIDE is a special use-case. It allows setting a branch name to be used
        # during the checkout phase, only if it exists on the remote.
        #
        # This is useful for PR builds and testing where you want to use defaults for most repos
        # but need to test building of a series of repos with the same experimental branch
        #
        if TRY_BRANCH_OVERRIDE:
            retries = 3
            while retries:
                try:
                    if branch_exists_in_repository(self.origin, TRY_BRANCH_OVERRIDE):
                        gh_override = TRY_BRANCH_OVERRIDE
                except CallError:
                    retries -= 1
                    logger.debug(
                        'Failed to determine if %r branch exists for %r. Trying again', TRY_BRANCH_OVERRIDE, self.origin
                    )
                    if not retries:
                        logger.debug('Unable to determine if %r branch exists in 3 attempts.', TRY_BRANCH_OVERRIDE)
                else:
                    break

        return gh_override
