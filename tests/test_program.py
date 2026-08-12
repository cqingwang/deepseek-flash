import argparse
import subprocess
import unittest
from unittest import mock

import program


class ContainerStateTests(unittest.TestCase):
    def setUp(self):
        self.k = {
            "container": "deepseek-v4-flash-vllm-dspark-1",
            "worker_hostname": "spark-b",
            "worker_ssh": "chan@spark-b",
            "repo": "/opt/deepseek-flash",
            "compose_file": "/opt/deepseek-flash/docker-compose.dspark.yml",
            "env_file": "/opt/deepseek-flash/.env.dspark",
        }

    @mock.patch("program.subprocess.run")
    def test_running_query_does_not_treat_stopped_container_as_running(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["docker"], 0, stdout="other-container\n", stderr=""
        )

        self.assertFalse(program.container_running_local(self.k))
        self.assertEqual(run.call_args.args[0][:2], ["docker", "ps"])
        self.assertNotIn("-a", run.call_args.args[0])

    @mock.patch("program.compose_up")
    @mock.patch("program.os.path.isfile", return_value=True)
    @mock.patch("program.container_running_local", return_value=False)
    @mock.patch("program.node_role", return_value="worker")
    def test_ensure_restarts_stopped_worker(self, _role, _running, _isfile, compose_up):
        self.assertEqual(program.cmd_ensure(self.k, {}, []), 0)
        compose_up.assert_called_once_with(
            self.k,
            {"NODE_RANK": "1", "HEADLESS": "1", "VLLM_HOST_IP": ""},
            service="vllm-dspark",
        )


class CliValidationTests(unittest.TestCase):
    def test_live_check_rejects_negative_wait(self):
        with self.assertRaises(SystemExit):
            program.build_parser().parse_args(["live_check", "--wait", "-1"])

    def test_chat_verify_rejects_zero_target(self):
        with self.assertRaises(SystemExit):
            program.build_parser().parse_args(["chat_verify", "0"])

    def test_positive_and_non_negative_types(self):
        self.assertEqual(program.positive_int("1"), 1)
        self.assertEqual(program.non_negative_int("0"), 0)
        with self.assertRaises(argparse.ArgumentTypeError):
            program.positive_int("0")
        with self.assertRaises(argparse.ArgumentTypeError):
            program.non_negative_int("-1")

    def test_announce_uses_stderr_for_machine_readable_commands(self):
        with mock.patch("sys.stderr") as stderr, mock.patch("builtins.print") as printer:
            program.logtask("test", "message")
        printer.assert_called_once()
        self.assertIs(printer.call_args.kwargs["file"], stderr)


if __name__ == "__main__":
    unittest.main()
