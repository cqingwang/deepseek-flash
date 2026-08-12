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


class ModelLinkLayoutTests(unittest.TestCase):
    """模型注册布局：宿主 /opt/models/<org>/<model> → symlink model_links/<short> → 容器内 /cache/huggingface/models/<short>。"""

    def setUp(self):
        self.cfg = {
            "common": {
                "model_lib": "/opt/models",
                "model_links": "/opt/models/models",
                "master_port": 25000,
                "vllm_image": "ghcr.io/anemll/dspark-vllm-gx10:0.1.1",
            },
            "head": {"fabric_ip": "10.100.240.1", "hca": "rocep1s0f0", "ifname": "enp1s0f0np0"},
            "worker": {"fabric_ip": "10.100.240.2", "management_ip": "10.100.240.2",
                       "hca": "rocep1s0f0", "ifname": "enp1s0f0np0"},
        }

    def test_gen_env_model_official_uses_single_short_per_main_template(self):
        env = program.gen_env(self.cfg, "/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731", template={})
        # main 分支 .env.dspark 模板约定：DSPARK_MODEL_OFFICIAL=/cache/huggingface/models/<HF_MODEL_SHORT>（单层）
        self.assertIn(
            "DSPARK_MODEL_OFFICIAL=/cache/huggingface/models/DeepSeek-V4-Flash-0731", env)
        self.assertIn(
            "DSPARK_ENCODING_FILE=/cache/huggingface/models/DeepSeek-V4-Flash-0731/encoding/encoding_dsv4.py", env)

    @mock.patch("program.ssh_task")
    @mock.patch("program.dotask")
    @mock.patch("program.os.path.isfile", return_value=True)
    def test_link_model_registers_single_short_symlink_to_org_model_dir(self, _isfile, dotask, _ssh):
        k = {"model_links": "/opt/models/models", "model_lib": "/opt/models",
             "worker_ssh": "chan@spark-b"}
        program.link_model(k, "/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731")
        ln_calls = [c for c in dotask.call_args_list if c.args[0] == "sudo ln -sfn"]
        self.assertEqual(
            ln_calls[0].args[1],
            ["/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731",
             "/opt/models/models/DeepSeek-V4-Flash-0731"])


if __name__ == "__main__":
    unittest.main()
