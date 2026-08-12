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
            "project": "deepseek-v4-flash",
            "api_url": "http://127.0.0.1:8888/v1/models",
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

    @mock.patch("program.ssh_task")
    def test_remote_running_query_uses_docker_ps_without_a(self, ssh):
        ssh.return_value = subprocess.CompletedProcess(["ssh"], 1, stdout="", stderr="")
        self.assertFalse(program.container_running_remote(self.k))
        self.assertIn("docker ps --format", ssh.call_args.args[1])
        self.assertNotIn("docker ps -a", ssh.call_args.args[1])

    @mock.patch("program.subprocess.run")
    def test_dotask_disables_capture_output_when_streams_are_given(self, run):
        run.return_value = subprocess.CompletedProcess(["true"], 0, stdout="", stderr="")
        program.dotask("true", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertFalse(run.call_args.kwargs["capture_output"])

    @mock.patch("program.dotask")
    def test_compose_global_options_precede_up(self, dotask):
        program.compose_up(self.k, {"NODE_RANK": "1"}, service="vllm-dspark")
        command = dotask.call_args.args[0]
        args = dotask.call_args.args[1]
        self.assertEqual(command, "docker compose")
        self.assertEqual(args[-3:], ["up", "-d", "vllm-dspark"])
        self.assertEqual(args[0], "-p")

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

    @mock.patch("program.dotask")
    @mock.patch("program.container_running_remote", return_value=False)
    @mock.patch("program.container_exists_local", return_value=False)
    @mock.patch("program.api_healthy", return_value=True)
    @mock.patch("program.node_role", return_value="head")
    def test_start_skips_healthy_api_before_script_probe(
        self, _role, _healthy, _head_exists, _worker_running, dotask
    ):
        self.assertEqual(program.cmd_start(self.k, {}, []), 0)
        dotask.assert_not_called()


class CliValidationTests(unittest.TestCase):
    def test_doctor_command_parses(self):
        parser = program.build_parser()
        self.assertEqual(parser.parse_args(["doctor"]).command, "doctor")

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


class ConfigurationBehaviorTests(unittest.TestCase):
    def test_resolve_model_uses_configured_model_root(self):
        consts = {
            "model_lib": "/srv/models",
            "default_model": "/srv/models/org/model",
        }
        self.assertEqual(program.resolve_model(consts, "org/other"), "/srv/models/org/other")

    def test_resolve_model_rejects_path_escape(self):
        consts = {"model_lib": "/srv/models", "default_model": "/srv/models/org/model"}
        with self.assertRaises(SystemExit):
            program.resolve_model(consts, "../outside")

    def test_installed_model_name_prefers_generated_env(self):
        consts = {"env_file": "/tmp/nonexistent-env", "default_model": "/srv/models/default"}
        with mock.patch("builtins.open", mock.mock_open(read_data="SERVED_MODEL_NAME=custom-model\n")):
            self.assertEqual(program.installed_model_name(consts), "custom-model")

    @mock.patch("program.ssh_task")
    @mock.patch("program.dotask")
    def test_doctor_checks_real_default_model_before_symlink_registration(self, dotask, ssh):
        consts = {
            "default_model": "/srv/models/org/model",
            "model_links": "/srv/models/models",
        }
        dotask.return_value = subprocess.CompletedProcess(["du"], 0, stdout="170000000001\n", stderr="")
        ssh.return_value = subprocess.CompletedProcess(["ssh"], 0, stdout="170000000001\n", stderr="")
        ok_messages = []
        bad_messages = []
        program.doctor_model(consts, "chan@worker", ok_messages.append, bad_messages.append)
        self.assertFalse(bad_messages)
        self.assertIn("/srv/models/org/model", dotask.call_args.args[0])
        self.assertNotIn("/srv/models/models", dotask.call_args.args[0])


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
