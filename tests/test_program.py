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
            "runtime_repo": "/opt/deepseek-flash/dspark",
            "compose_file": "/opt/deepseek-flash/dspark/docker-compose.dspark.yml",
            "env_file": "/opt/deepseek-flash/dspark/.env.dspark",
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

    @mock.patch("program.open", new_callable=mock.mock_open,
                 read_data="WORKER_HOST=192.168.2.161\nMASTER_ADDR=10.100.240.1\nMASTER_PORT=25000\n")
    def test_recovery_env_matches_main_explicit_head_values(self, _open):
        values = program.recovery_env(self.k)
        self.assertEqual(values["WORKER_HOST"], "192.168.2.161")
        self.assertEqual(values["MASTER_ADDR"], "10.100.240.1")
        self.assertEqual(values["VLLM_HOST"], "127.0.0.1")
        self.assertEqual(values["VLLM_HOST_IP"], "10.100.240.1")

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
    @mock.patch("program.os.access", return_value=True)
    @mock.patch("program.api_healthy", return_value=True)
    @mock.patch("program.node_role", return_value="head")
    def test_start_skips_healthy_api_before_script_probe(
        self, _role, _healthy, _executable, _head_exists, _worker_running, dotask
    ):
        self.assertEqual(program.cmd_start(self.k, {}, []), 0)
        dotask.assert_not_called()

    @mock.patch("program.api_healthy")
    @mock.patch("program.logtask")
    @mock.patch("program.os.access", return_value=False)
    @mock.patch("program.node_role", return_value="head")
    def test_start_requires_upstream_script_before_api_probe(self, _role, _executable, logtask, api_healthy):
        def fail_on_missing(action, desc="", level=program.LogLevel.INFO):
            if "缺少可执行的" in action:
                raise SystemExit(1)

        logtask.side_effect = fail_on_missing
        with self.assertRaises(SystemExit):
            program.cmd_start(self.k, {}, [])
        api_healthy.assert_not_called()

    @mock.patch("program.dotask")
    @mock.patch("program.os.access", return_value=False)
    @mock.patch("program.node_role", return_value="head")
    def test_stop_fails_when_upstream_script_is_missing(self, _role, _executable, dotask):
        with self.assertRaises(SystemExit):
            program.cmd_stop(self.k, {}, [])
        dotask.assert_not_called()

    @mock.patch("program.cmd_start", return_value=0)
    @mock.patch("program.cmd_stop")
    def test_restart_forwards_config_to_nested_commands(self, stop, start):
        cfg = {"common": {"repo": "/opt/deepseek-flash"}}
        self.k["config_local"] = "/etc/dspark-vllm/config.yaml"
        self.assertEqual(program.cmd_restart(self.k, cfg, []), 0)
        stop.assert_called_once_with(self.k, cfg, [])
        start.assert_called_once_with(self.k, cfg, [])

    @mock.patch("program.activate_units")
    @mock.patch("program.wait_for_api", return_value=True)
    @mock.patch("program.cmd_start", return_value=0)
    @mock.patch("program.install_env")
    @mock.patch("program.link_model")
    @mock.patch("program.container_exists_remote", return_value=False)
    @mock.patch("program.container_exists_local", return_value=False)
    @mock.patch("program.deploy_units")
    @mock.patch("program.deploy_ops")
    @mock.patch("program.validate_runtime_repo")
    @mock.patch("program.os.path.isfile", return_value=True)
    def test_install_forwards_config_to_nested_start(
        self, _isfile, _validate, _deploy_ops, _deploy_units,
        _head_exists, _worker_exists, _link_model, _install_env,
        start, _wait, _activate,
    ):
        consts = dict(self.k, config_local="/etc/dspark-vllm/config.yaml",
                      default_model="/opt/models/org/model", model_lib="/opt/models")
        cfg = {"common": {"repo": "/opt/deepseek-flash"}}
        args = argparse.Namespace(model=None)
        self.assertEqual(program.cmd_install(consts, cfg, args), 0)
        start.assert_called_once_with(consts, cfg, [])


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
    def test_parser_constants_derives_runtime_files_from_runtime_repo(self):
        cfg = {
            "common": {
                "user": "chan",
                "repo": "/opt/deepseek-flash",
                "runtime_repo": "/opt/deepseek-flash/dspark",
                "project": "deepseek-v4-flash",
                "container": "deepseek-v4-flash-vllm-dspark-1",
                "model_lib": "/opt/models",
                "model_links": "/opt/models/models",
                "default_model": "/opt/models/org/model",
                "vllm_image": "image:tag",
                "api_url": "http://127.0.0.1:8888/v1/models",
            },
            "head": {"hostname": "head", "fabric_ip": "10.0.0.1"},
            "worker": {"hostname": "worker", "ssh": "chan@worker"},
        }
        consts = program.parser_constants(cfg)
        self.assertEqual(consts["runtime_repo"], "/opt/deepseek-flash/dspark")
        self.assertEqual(consts["env_file"], "/opt/deepseek-flash/dspark/.env.dspark")
        self.assertEqual(consts["compose_file"], "/opt/deepseek-flash/dspark/docker-compose.dspark.yml")

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

    def test_runtime_repo_paths_are_separate_from_model_library(self):
        consts = {
            "repo": "/opt/deepseek-flash",
            "runtime_repo": "/opt/deepseek-flash/dspark",
            "model_lib": "/opt/models",
            "compose_file": "/opt/deepseek-flash/dspark/docker-compose.dspark.yml",
        }
        files = program.runtime_repo_files(consts)
        self.assertEqual(files["start"], "/opt/deepseek-flash/dspark/start-deepseek-v4-flash-dspark.sh")
        self.assertTrue(all(path.startswith("/opt/deepseek-flash/dspark/") for path in files.values()))
        self.assertNotIn("/opt/models", files["start"])

    @mock.patch("program.logtask")
    @mock.patch("program.ssh_task")
    @mock.patch("program.os.access", return_value=True)
    @mock.patch("program.os.path.isfile", return_value=True)
    def test_validate_runtime_repo_checks_worker_before_install(self, _isfile, _access, ssh, logtask):
        ssh.side_effect = [
            subprocess.CompletedProcess(["ssh"], 1, stdout="", stderr=""),
            subprocess.CompletedProcess(["ssh"], 1, stdout="", stderr=""),
            subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["ssh"], 1, stdout="", stderr=""),
        ]
        logtask.side_effect = SystemExit(1)
        with self.assertRaises(SystemExit):
            program.validate_runtime_repo({
                "runtime_repo": "/opt/deepseek-flash/dspark",
                "compose_file": "/opt/deepseek-flash/dspark/docker-compose.dspark.yml",
            }, "chan@worker")
        self.assertIn("WORKER 缺少 MiaAI 部署运行时文件", logtask.call_args.args[0])

    def test_compose_uses_runtime_repo_as_working_directory(self):
        consts = {
            "project": "deepseek-v4-flash",
            "runtime_repo": "/opt/deepseek-flash/dspark",
            "env_file": "/opt/deepseek-flash/dspark/.env.dspark",
            "compose_file": "/opt/deepseek-flash/dspark/docker-compose.dspark.yml",
        }
        with mock.patch("program.dotask") as dotask:
            program.compose_up(consts, {"NODE_RANK": "0"})
        self.assertEqual(dotask.call_args.kwargs["cwd"], consts["runtime_repo"])
        self.assertIn(consts["compose_file"], dotask.call_args.args[1])

    @mock.patch("program.ssh_task")
    @mock.patch("program.os.access", return_value=False)
    @mock.patch("program.os.path.isfile", return_value=False)
    def test_doctor_reports_each_missing_runtime_file(self, _isfile, _access, ssh):
        ssh.return_value = subprocess.CompletedProcess(["ssh"], 1, stdout="", stderr="")
        consts = {
            "repo": "/opt/deepseek-flash",
            "runtime_repo": "/opt/deepseek-flash/dspark",
            "compose_file": "/opt/deepseek-flash/dspark/docker-compose.dspark.yml",
        }
        ok_messages = []
        bad_messages = []
        program.doctor_runtime_repo(consts, "chan@worker", ok_messages.append, bad_messages.append)
        self.assertTrue(any("docker-compose.dspark.yml" in message for message in bad_messages))
        self.assertTrue(any("start-deepseek-v4-flash-dspark.sh" in message for message in bad_messages))
        self.assertTrue(any("stop-deepseek-v4-flash-dspark.sh" in message for message in bad_messages))
        self.assertTrue(any("DOWNLOADS.md 第 9 项" in message for message in bad_messages))

    def test_model_required_files_match_download_manifest_core(self):
        required = program.model_required_files("/opt/models/org/model")
        self.assertIn("/opt/models/org/model/config.json", required)
        self.assertIn("/opt/models/org/model/encoding/encoding_dsv4.py", required)
        self.assertIn("/opt/models/org/model/model-00001-of-00048.safetensors", required)
        self.assertIn("/opt/models/org/model/model-00048-of-00048.safetensors", required)
        self.assertEqual(sum(path.endswith(".safetensors") for path in required), 48)

    @mock.patch("program.ssh_task")
    @mock.patch("program.dotask")
    @mock.patch("program.os.path.isfile", return_value=True)
    def test_doctor_checks_real_default_model_before_symlink_registration(self, _isfile, dotask, ssh):
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
