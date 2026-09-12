import contextlib
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

from upload_final_delivery import publish_refs, remote_content_verification, run


class FinalDeliveryUploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / '协作 repo'
        self.remote = self.root / 'remote.git'
        self.session = self.root / 'upload_session'
        self.session.mkdir()
        self.call('git', 'init', '--bare', '--initial-branch=main', self.remote)
        self.call('git', 'init', '--initial-branch=main', self.repo)
        self.g('config', 'user.name', 'URSS integration test')
        self.g('config', 'user.email', 'test@example.invalid')
        (self.repo / 'source.txt').write_text('preserved source\n')
        self.g('add', 'source.txt')
        self.g('commit', '-m', 'Baseline')
        self.base = self.g('rev-parse', 'HEAD').strip()
        self.g('remote', 'add', 'origin', self.remote)
        self.g('push', 'origin', 'HEAD:refs/heads/main')
        (self.repo / 'artifact.bin').write_bytes(b'raw experiment bytes\x8f\x00\xff')
        self.g('add', 'artifact.bin')
        self.g('commit', '-m', 'Local results')
        self.final = self.g('rev-parse', 'HEAD').strip()
        data = (self.repo / 'artifact.bin').read_bytes()
        self.meta = dict(delivery_commit=self.final, delivery_branch='delivery/test',
                         default_branch='main', preserve_tags={'urss-old-code': self.base},
                         remote_files=[dict(path='artifact.bin', size_bytes=len(data),
                                            sha256=hashlib.sha256(data).hexdigest())])

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, *args):
        result = subprocess.run([str(a) for a in args], check=True, capture_output=True)
        return result.stdout.decode('utf-8', errors='replace')

    def g(self, *args):
        return self.call('git', '-C', self.repo, *args)

    def remote_oid(self, name):
        return self.call('git', '-C', self.remote, 'rev-parse', name).strip()

    def publish(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return publish_refs(self.repo, self.meta, self.session)

    def test_fast_forward_keeps_history_remote_bytes_and_resume(self):
        status, refs = self.publish()
        self.assertEqual(status, 'PASS')
        self.assertEqual(self.remote_oid('main'), self.final)
        self.assertEqual(refs['refs/tags/urss-old-code'], self.base)
        with contextlib.redirect_stdout(io.StringIO()):
            results = remote_content_verification(self.repo, str(self.remote), self.meta, self.session)
        self.assertTrue(results[0]['remote_bytes_verified'])
        self.assertEqual(self.publish()[0], 'PASS')

    def test_diverged_main_is_preserved_while_results_are_uploaded(self):
        self.g('checkout', '-b', 'parallel', self.base)
        (self.repo / 'parallel.txt').write_text('collaborator work\n')
        self.g('add', 'parallel.txt')
        self.g('commit', '-m', 'Parallel work')
        parallel = self.g('rev-parse', 'HEAD').strip()
        self.g('push', 'origin', 'HEAD:refs/heads/main')
        self.g('checkout', 'main')
        status, refs = self.publish()
        self.assertEqual(status, 'MERGE_REVIEW_REQUIRED')
        self.assertEqual(self.remote_oid('main'), parallel)
        self.assertEqual(refs['refs/heads/delivery/test'], self.final)

    @unittest.skipIf(__import__('os').name == 'nt', 'POSIX Git receive hook fixture')
    def test_protected_main_falls_back_to_review_branch(self):
        hook = self.remote / 'hooks/update'
        hook.write_text('#!/bin/sh\nif [ "$1" = "refs/heads/main" ]; then exit 1; fi\nexit 0\n')
        hook.chmod(0o755)
        status, refs = self.publish()
        self.assertEqual(status, 'MERGE_REVIEW_REQUIRED')
        self.assertEqual(self.remote_oid('main'), self.base)
        self.assertEqual(refs['refs/heads/delivery/test'], self.final)
        self.assertEqual(refs['refs/tags/urss-old-code'], self.base)

    def test_existing_tag_collision_prevents_any_publication(self):
        self.g('push', 'origin', self.final + ':refs/tags/urss-old-code')
        with self.assertRaisesRegex(RuntimeError, 'archive tag'):
            self.publish()
        self.assertEqual(self.remote_oid('main'), self.base)
        refs = self.g('ls-remote', 'origin', 'refs/heads/delivery/test')
        self.assertEqual(refs, '')

    def test_remote_verification_rejects_wrong_archive_digest(self):
        self.publish()
        self.meta['remote_files'][0]['sha256'] = '0' * 64
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Remote file verification failed'):
                remote_content_verification(self.repo, str(self.remote), self.meta, self.session)

    def test_non_utf8_git_style_diagnostics_do_not_abort_the_stage(self):
        import sys
        result = run([sys.executable, '-c', 'import sys; sys.stderr.buffer.write(bytes([0x8f]))'])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '\ufffd')


if __name__ == '__main__':
    unittest.main()
