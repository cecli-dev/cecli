import gc
import os
import weakref

import pytest

from cecli.coders import Coder
from cecli.helpers.file_system import FileSystemService
from cecli.io import InputOutput
from cecli.repo import GitRepoProxy
from cecli.utils import GitTemporaryDirectory


@pytest.fixture(autouse=True)
def reset_registries():
    FileSystemService.reset_instance()
    GitRepoProxy.reset_instances()
    yield
    FileSystemService.reset_instance()
    GitRepoProxy.reset_instances()


class TestFileSystemServicePerRoot:
    def test_for_root_caches_per_base_path(self):
        with GitTemporaryDirectory() as root:
            first = FileSystemService.for_root(root)
            again = FileSystemService.for_root(root)

            assert first is again
            assert FileSystemService._normalize_root(root) in FileSystemService._instances

    def test_for_root_distinct_for_distinct_base_paths(self):
        with GitTemporaryDirectory() as root_a, GitTemporaryDirectory() as root_b:
            service_a = FileSystemService.for_root(root_a)
            service_b = FileSystemService.for_root(root_b)

            assert service_a is not service_b
            assert service_a.root.rstrip("/") == root_a.rstrip("/")
            assert service_b.root.rstrip("/") == root_b.rstrip("/")

    def test_get_instance_returns_active_root(self):
        with GitTemporaryDirectory() as root_a, GitTemporaryDirectory() as root_b:
            service_a = FileSystemService.for_root(root_a)
            service_b = FileSystemService.for_root(root_b)

            assert FileSystemService.get_instance() is service_b
            assert FileSystemService.get_instance() is not service_a

    def test_evict_removes_root(self):
        with GitTemporaryDirectory() as root:
            FileSystemService.for_root(root)
            key = FileSystemService._normalize_root(root)
            assert key in FileSystemService._instances

            FileSystemService.evict(root)
            assert key not in FileSystemService._instances


class TestGitRepoProxyPerRoot:
    def test_for_root_caches_per_base_path(self):
        with GitTemporaryDirectory() as root:
            io = InputOutput(pretty=False, yes=True)
            proxy_a = GitRepoProxy.for_root(None, io, fnames=[root])
            proxy_b = GitRepoProxy.for_root(None, io, fnames=[root])

            assert proxy_a is proxy_b

    def test_for_root_distinct_for_distinct_base_paths(self):
        with GitTemporaryDirectory() as root_a, GitTemporaryDirectory() as root_b:
            io = InputOutput(pretty=False, yes=True)
            proxy_a = GitRepoProxy.for_root(None, io, fnames=[root_a])
            proxy_b = GitRepoProxy.for_root(None, io, fnames=[root_b])

            assert proxy_a is not proxy_b
            assert proxy_a.root.rstrip("/") == root_a.rstrip("/")
            assert proxy_b.root.rstrip("/") == root_b.rstrip("/")

    def test_for_root_with_explicit_root_caches(self):
        with GitTemporaryDirectory() as root:
            io = InputOutput(pretty=False, yes=True)
            proxy = GitRepoProxy.for_root(root, io)

            assert proxy.root.rstrip("/") == root.rstrip("/")
            assert GitRepoProxy.for_root(root, io) is proxy


class TestAutomaticCleanup:
    """The per-root service is released when the last coder sharing it dies."""

    class _FakeCoder:
        def __init__(self, root):
            self.root = root
            self.repo = GitRepoProxy.for_root(
                None, InputOutput(pretty=False, yes=True), fnames=[root]
            )
            self.fs = FileSystemService.for_root(root, repo=self.repo)
            self._fs_key = FileSystemService._normalize_root(root)
            FileSystemService._inc_ref(self._fs_key)
            weakref.finalize(self, FileSystemService._release, self._fs_key)

    def test_last_coder_gc_evicts_service_and_repo(self):
        with GitTemporaryDirectory() as root:
            key = FileSystemService._normalize_root(root)
            coder = self._FakeCoder(root)

            assert FileSystemService._refcounts.get(key) == 1
            assert key in FileSystemService._instances
            assert key in GitRepoProxy._instances

            del coder
            gc.collect()

            assert key not in FileSystemService._instances
            assert key not in GitRepoProxy._instances
            assert FileSystemService._refcounts.get(key, 0) == 0

    def test_shared_root_kept_alive_until_last_coder_dies(self):
        with GitTemporaryDirectory() as root:
            key = FileSystemService._normalize_root(root)
            coder_a = self._FakeCoder(root)
            coder_b = self._FakeCoder(root)

            assert coder_a.fs is coder_b.fs
            assert coder_a.repo is coder_b.repo
            assert FileSystemService._refcounts.get(key) == 2

            del coder_b
            gc.collect()
            assert key in FileSystemService._instances
            assert key in GitRepoProxy._instances
            assert FileSystemService._refcounts.get(key) == 1

            del coder_a
            gc.collect()
            assert key not in FileSystemService._instances
            assert key not in GitRepoProxy._instances
            assert FileSystemService._refcounts.get(key, 0) == 0


class TestCoderIntegration:
    async def test_coder_gets_per_root_fs_and_repo(self, gpt35_model):
        with GitTemporaryDirectory() as root_a:
            io = InputOutput(pretty=False, yes=True)
            coder_a = await Coder.create(gpt35_model, None, io)
        with GitTemporaryDirectory() as root_b:
            coder_b = await Coder.create(gpt35_model, None, io)

        assert coder_a.fs is not coder_b.fs
        assert coder_a.repo is not coder_b.repo
        assert coder_a.fs.repo is coder_a.repo
        assert coder_b.fs.repo is coder_b.repo
        assert coder_a.root.rstrip("/") == root_a.rstrip("/")
        assert coder_b.root.rstrip("/") == root_b.rstrip("/")


class TestRootOverride:
    """Validates the sub-agent root override and primary_root retention."""

    async def test_root_kwarg_overrides_working_dir(self, gpt35_model):
        with GitTemporaryDirectory() as root_a:
            os.chdir(root_a)
            nested = os.path.join(root_a, "nested")
            os.makedirs(nested, exist_ok=True)
            io = InputOutput(pretty=False, yes=True)

            coder = await Coder.create(gpt35_model, None, io, root=nested)

            assert os.path.normpath(coder.root) == os.path.normpath(nested)
            assert coder.primary_root == coder.root
            assert coder.fs is FileSystemService.for_root(nested, repo=coder.repo)

    async def test_primary_root_propagated_from_parent(self, gpt35_model):
        with GitTemporaryDirectory():
            io = InputOutput(pretty=False, yes=True)
            parent = await Coder.create(gpt35_model, None, io)
            with GitTemporaryDirectory() as root_b:
                child = await Coder.create(from_coder=parent, root=root_b, io=io)

                assert child.primary_root.rstrip("/") == parent.root.rstrip("/")
                assert child.root.rstrip("/") == root_b.rstrip("/")
                assert child.fs is not parent.fs

    async def test_sub_agent_repo_scoped_to_its_root(self, gpt35_model):
        with GitTemporaryDirectory():
            io = InputOutput(pretty=False, yes=True)
            parent = await Coder.create(gpt35_model, None, io)
            with GitTemporaryDirectory() as root_b:
                child = await Coder.create(from_coder=parent, root=root_b, io=io)

                assert child.root.rstrip("/") == root_b.rstrip("/")
                assert child.repo.root.rstrip("/") == root_b.rstrip("/")
                assert child.fs.repo.root.rstrip("/") == root_b.rstrip("/")

    async def test_resolve_relative_to_primary_root(self, gpt35_model):
        with GitTemporaryDirectory() as root_a:
            os.chdir(root_a)
            io = InputOutput(pretty=False, yes=True)
            coder = await Coder.create(gpt35_model, None, io)
            base = coder.primary_root or coder.root

            resolved = coder.resolve_relative_to_primary_root("skills/mine")
            assert resolved == os.path.normpath(os.path.join(base, "skills/mine"))

            abs_path = "/tmp/abs-skill"
            assert coder.resolve_relative_to_primary_root(abs_path) == abs_path
            assert coder.resolve_relative_to_primary_root("") == ""
