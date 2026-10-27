from unittest import TestCase,mock
import runtime_liveness as module

class RuntimeMemoryTests(TestCase):
    def test_linux_rss_and_cgroup_are_separate_scopes(self):
        values={'/proc/self/statm':'100 4 0','/sys/fs/cgroup/memory.current':'268435456','/sys/fs/cgroup/memory.max':'536870912'}
        with mock.patch.object(module,'_small_text',side_effect=lambda p:values[p]),mock.patch.object(module.os,'sysconf',return_value=4096):
            r=module.memory_usage()
        self.assertEqual(r['process_rss_bytes'],16384)
        self.assertEqual(r['container_current_bytes'],268435456)
        self.assertEqual(r['container_limit_bytes'],536870912)
        self.assertEqual(r['container_utilization_pct'],50.)

    def test_missing_or_unlimited_values_are_null_not_zero_usage(self):
        with mock.patch.object(module,'_small_text',return_value='max'):
            r=module.memory_usage()
        for key in ('process_rss_bytes','container_current_bytes','container_limit_bytes','container_utilization_pct'):
            self.assertIsNone(r[key])

    def test_invalid_values_do_not_crash_liveness(self):
        with mock.patch.object(module,'_small_text',return_value='-1'):
            r=module.memory_usage()
        self.assertIsNone(r['container_current_bytes'])
        self.assertIsNone(r['container_limit_bytes'])

    def test_file_reads_are_bounded_and_failures_do_not_propagate(self):
        handle=mock.MagicMock();handle.__enter__.return_value=handle;handle.read.return_value='10'
        with mock.patch.object(module.Path,'open',return_value=handle):
            self.assertEqual(module._small_text('ignored'),'10')
        handle.read.assert_called_once_with(128)
        with mock.patch.object(module.Path,'open',side_effect=OSError()):
            self.assertEqual(module._small_text('ignored'),'')
