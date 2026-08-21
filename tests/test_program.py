import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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
            "perf_api_url": "http://192.168.2.180:8888/v1/models",
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

    @mock.patch("program.open", new_callable=mock.mock_open, read_data=(
        "ABLITERATED=1\nDSPARK_MODEL_OFFICIAL=/models/official\n"
        "DSPARK_MODEL_ABLITERATED=/models/abliterated\nDSPARK_REVISION=\n"
        "DSPARK_ENCODING_FILE=/models/abliterated/encoding/encoding_dsv4.py\n"
        "MASTER_ADDR=10.100.240.1\n"
    ))
    def test_recovery_env_selects_local_abliterated_model(self, _open):
        values = program.recovery_env(self.k)
        self.assertEqual(values["DSPARK_MODEL"], "/models/abliterated")
        self.assertEqual(values["DSPARK_ENCODING_FILE"], "/models/abliterated/encoding/encoding_dsv4.py")

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

    @mock.patch("program.dotask")
    @mock.patch("program.container_running_remote", return_value=False)
    @mock.patch("program.container_exists_local", return_value=False)
    @mock.patch("program.api_healthy", return_value=False)
    @mock.patch("program.os.access", return_value=True)
    @mock.patch("program.node_role", return_value="head")
    def test_start_streams_upstream_diagnostics(
        self, _role, _executable, _healthy, _head_exists, _worker_running, dotask
    ):
        self.assertEqual(program.cmd_start(self.k, {}, []), 0)
        self.assertEqual(dotask.call_args.kwargs["stdout"], None)
        self.assertEqual(dotask.call_args.kwargs["stderr"], None)

    @mock.patch("program.wait_for_api", return_value=True)
    @mock.patch("program.api_healthy", return_value=False)
    @mock.patch("program.dotask")
    @mock.patch("program.container_running_remote", return_value=False)
    @mock.patch("program.container_exists_local", return_value=False)
    @mock.patch("program.os.access", return_value=True)
    @mock.patch("program.node_role", return_value="head")
    def test_start_treats_existing_container_exit_three_as_success_when_api_recovers(
        self, _role, _executable, _head_exists, _worker_running, dotask, _healthy, wait_for_api
    ):
        dotask.side_effect = subprocess.CalledProcessError(3, ["start-script"])

        self.assertEqual(program.cmd_start(self.k, {}, []), 0)
        wait_for_api.assert_called_once_with(self.k)

    @mock.patch("program.wait_for_api", return_value=False)
    @mock.patch("program.api_healthy", return_value=False)
    @mock.patch("program.dotask")
    @mock.patch("program.container_running_remote", return_value=False)
    @mock.patch("program.container_exists_local", return_value=False)
    @mock.patch("program.os.access", return_value=True)
    @mock.patch("program.node_role", return_value="head")
    def test_start_fails_existing_container_exit_three_when_api_stays_down(
        self, _role, _executable, _head_exists, _worker_running, dotask, _healthy, _wait_for_api
    ):
        dotask.side_effect = subprocess.CalledProcessError(3, ["start-script"])

        with self.assertRaises(SystemExit) as raised:
            program.cmd_start(self.k, {}, [])
        self.assertEqual(raised.exception.code, 1)

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

    @mock.patch("program.container_running_remote", return_value=False)
    @mock.patch("program.dotask")
    @mock.patch("program.os.access", return_value=True)
    @mock.patch("program.node_role", return_value="head")
    def test_stop_injects_worker_host_from_config_when_runtime_env_is_missing(
        self, _role, _executable, dotask, _worker_running
    ):
        dotask.return_value = subprocess.CompletedProcess(["stop"], 0, stdout="", stderr="")
        cfg = {"worker": {"management_ip": "192.168.2.180"}}

        self.assertEqual(program.cmd_stop(self.k, cfg, []), 0)

        stop_call = dotask.call_args_list[0]
        self.assertEqual(stop_call.kwargs["env"]["WORKER_HOST"], "192.168.2.180")
        self.assertEqual(stop_call.kwargs["cwd"], self.k["runtime_repo"])

    @mock.patch("program.cmd_start", return_value=0)
    @mock.patch("program.cmd_stop")
    def test_restart_forwards_config_to_nested_commands(self, stop, start):
        cfg = {"common": {"repo": "/opt/deepseek-flash"}}
        self.k["config_local"] = "/etc/dspark-vllm/config.yaml"
        self.assertEqual(program.cmd_restart(self.k, cfg, []), 0)
        stop.assert_called_once_with(self.k, cfg, [])
        start.assert_called_once_with(self.k, cfg, [])

    @mock.patch("program.cmd_start", return_value=0)
    @mock.patch("program.wait_for_api", return_value=True)
    @mock.patch("program.install_env")
    @mock.patch("program.container_exists_remote", return_value=False)
    @mock.patch("program.container_exists_local", return_value=False)
    @mock.patch("program.deploy_units")
    @mock.patch("program.deploy_ops")
    @mock.patch("program.validate_runtime_repo")
    @mock.patch("program.os.path.isfile", return_value=True)
    def test_install_forwards_config_to_nested_start(
        self, _isfile, _validate, _deploy_ops, _deploy_units,
        _head_exists, _worker_exists, _install_env,
        _wait, start,
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

    def test_fetch_requires_model_repo_id(self):
        parser = program.build_parser()
        args = parser.parse_args(["fetch", "deepseek-ai/DeepSeek-V4-Flash-0731"])
        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.model, "deepseek-ai/DeepSeek-V4-Flash-0731")
        with self.assertRaises(SystemExit):
            parser.parse_args(["fetch"])

    def test_fetch_downloads_to_configured_model_library(self):
        with tempfile.TemporaryDirectory() as model_lib:
            consts = {"model_lib": model_lib}
            args = argparse.Namespace(model="org/variant")
            def run_download(_cmd, command_args, **_kwargs):
                destination = command_args[command_args.index("--destination") + 1]
                Path(destination, "config.json").parent.mkdir(parents=True, exist_ok=True)
                Path(destination, "config.json").write_text("{}", encoding="utf-8")

            with mock.patch("program.dotask", side_effect=run_download) as dotask:
                self.assertEqual(program.cmd_fetch(consts, {}, args), 0)

            command = dotask.call_args.args[1]
            self.assertEqual(command[command.index("--repo-id") + 1], "org/variant")
            self.assertEqual(command[command.index("--destination") + 1], str(Path(model_lib, "org", "variant")))
            self.assertEqual(command[command.index("--endpoint") + 1], "https://hf-mirror.com")

    def test_fetch_rejects_nested_or_traversal_repo_ids(self):
        consts = {"model_lib": "/tmp/models"}
        for model_id in ("org/nested/variant", "../variant", "org/../variant"):
            with self.subTest(model_id=model_id), self.assertRaises(SystemExit):
                program.resolve_fetch_target(consts, model_id)

    def test_display_command_accepts_only_on_or_off(self):
        parser = program.build_parser()
        self.assertEqual(parser.parse_args(["display", "off"]).mode, "off")
        self.assertEqual(parser.parse_args(["display", "on"]).mode, "on")
        with self.assertRaises(SystemExit):
            parser.parse_args(["display", "invalid"])

    def test_live_check_rejects_negative_wait(self):
        with self.assertRaises(SystemExit):
            program.build_parser().parse_args(["live_check", "--wait", "-1"])

    def test_perf_requires_thinking_mode_and_rejects_zero_target(self):
        args = program.build_parser().parse_args(["perf", "on", "10"])
        self.assertEqual(args.mode, "on")
        self.assertEqual(args.target, 10)
        self.assertEqual(program.build_parser().parse_args(["perf", "off"]).mode, "off")
        with self.assertRaises(SystemExit):
            program.build_parser().parse_args(["perf", "0"])
        with self.assertRaises(SystemExit):
            program.build_parser().parse_args(["perf", "on", "0"])

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


class DisplayModeTests(unittest.TestCase):
    def setUp(self):
        self.k = {
            "head_hostname": "spark-a",
            "worker_ssh": "chan@spark-b",
        }

    @mock.patch("program.ssh_task")
    @mock.patch("program.dotask")
    @mock.patch("program.node_role", return_value="head")
    @mock.patch("program.socket.gethostname", return_value="spark-a")
    def test_display_off_sets_multi_user_on_both_nodes(self, _hostname, _role, dotask, ssh):
        self.assertEqual(program.cmd_display(self.k, {}, argparse.Namespace(mode="off")), 0)
        dotask.assert_called_once_with("sudo systemctl set-default", ["multi-user.target"], check=True)
        ssh.assert_called_once_with(
            "chan@spark-b", "sudo systemctl set-default multi-user.target", check=True
        )

    @mock.patch("program.ssh_task")
    @mock.patch("program.dotask")
    @mock.patch("program.node_role", return_value="head")
    @mock.patch("program.socket.gethostname", return_value="spark-a")
    def test_display_on_sets_graphical_on_both_nodes(self, _hostname, _role, dotask, ssh):
        self.assertEqual(program.cmd_display(self.k, {}, argparse.Namespace(mode="on")), 0)
        dotask.assert_called_once_with("sudo systemctl set-default", ["graphical.target"], check=True)
        ssh.assert_called_once_with(
            "chan@spark-b", "sudo systemctl set-default graphical.target", check=True
        )


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
                "default_model": "/opt/models/org/model",
                "vllm_image": "image:tag",
                "api_url": "http://127.0.0.1:8888/v1/models",
            },
            "head": {"hostname": "head", "management_ip": "192.168.2.180", "fabric_ip": "10.0.0.1"},
            "worker": {"hostname": "worker", "ssh": "chan@worker"},
        }
        consts = program.parser_constants(cfg)
        self.assertEqual(consts["runtime_repo"], "/opt/deepseek-flash/dspark")
        self.assertEqual(consts["env_file"], "/opt/deepseek-flash/dspark/.env.dspark")
        self.assertEqual(consts["compose_file"], "/opt/deepseek-flash/dspark/docker-compose.dspark.yml")
        self.assertEqual(consts["perf_api_url"], "http://192.168.2.180:8888/v1/models")

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

    def test_runtime_script_clears_hf_revision_for_local_model_paths(self):
        with open("dspark/start-deepseek-v4-flash-dspark.sh", encoding="utf-8") as script:
            content = script.read()
        self.assertIn('if [[ "$DSPARK_MODEL" = /* ]]; then', content)
        self.assertIn('DSPARK_REVISION=""', content)

    @mock.patch("program.ssh_task")
    @mock.patch("program.dotask")
    @mock.patch("program.os.path.isfile", return_value=True)
    def test_doctor_checks_real_default_model_before_symlink_registration(self, _isfile, dotask, ssh):
        consts = {
            "default_model": "/srv/models/org/model",
        }
        dotask.return_value = subprocess.CompletedProcess(["du"], 0, stdout="170000000001\n", stderr="")
        ssh.return_value = subprocess.CompletedProcess(["ssh"], 0, stdout="170000000001\n", stderr="")
        ok_messages = []
        bad_messages = []
        program.doctor_model(consts, "chan@worker", ok_messages.append, bad_messages.append)
        self.assertFalse(bad_messages)
        self.assertIn("/srv/models/org/model", dotask.call_args.args[0])
        self.assertNotIn("/srv/models/models", dotask.call_args.args[0])


class ModelMountLayoutTests(unittest.TestCase):
    """模型布局：宿主 /opt/models/<org>/<model> → 容器 /models/<org>/<model>。"""

    def setUp(self):
        self.cfg = {
            "common": {
                "model_lib": "/opt/models",
                "max_request": 6,
                "max_token": 1048576,
                "master_port": 25000,
                "vllm_image": "ghcr.io/anemll/dspark-vllm-gx10:0.1.1",
            },
            "head": {"fabric_ip": "10.100.240.1", "hca": "rocep1s0f0", "ifname": "enp1s0f0np0"},
            "worker": {"fabric_ip": "10.100.240.2", "management_ip": "10.100.240.2",
                       "hca": "rocep1s0f0", "ifname": "enp1s0f0np0"},
        }

    def test_gen_env_model_official_uses_single_short_per_main_template(self):
        env = program.gen_env(self.cfg, "/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731", template={})
        # 模型根目录直接映射到容器 /models，保留组织名和模型名两级路径。
        self.assertIn(
            "DSPARK_MODEL_OFFICIAL=/models/deepseek-ai/DeepSeek-V4-Flash-0731", env)
        self.assertIn(
            "DSPARK_ENCODING_FILE=/models/deepseek-ai/DeepSeek-V4-Flash-0731/encoding/encoding_dsv4.py", env)

    def test_gen_env_maps_config_capacity_to_runtime_env(self):
        env = program.gen_env(self.cfg, "/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731", template={})
        self.assertIn("MAX_NUM_SEQS=6", env)
        self.assertIn("MAX_MODEL_LEN=1048576", env)

    def test_gen_env_abliterated_selects_local_abliterated_lane_without_revision(self):
        cfg = {**self.cfg, "common": {**self.cfg["common"], "model_variant": "abliterated"}}
        env = program.gen_env(
            cfg,
            "/opt/models/drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32",
            template={},
        )
        self.assertIn("ABLITERATED=1", env)
        self.assertIn(
            "DSPARK_MODEL_ABLITERATED=/models/drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32",
            env,
        )
        self.assertIn("DSPARK_REVISION_ABLITERATED=", env)

    def test_install_defaults_use_one_m_context_and_six_sequences(self):
        with open("dspark.env.json", encoding="utf-8") as stream:
            template = json.load(stream)
        self.assertEqual(template["MAX_MODEL_LEN"], "1048576")
        self.assertEqual(template["MAX_NUM_SEQS"], "6")
        compose = Path("dspark/docker-compose.dspark.yml").read_text(encoding="utf-8")
        self.assertIn("--max-model-len ${MAX_MODEL_LEN:-1048576}", compose)
        self.assertIn("--max-num-seqs ${MAX_NUM_SEQS:-6}", compose)

    def test_gen_env_keeps_organization_and_model_path(self):
        env = program.gen_env(self.cfg, "/opt/models/drowzeys/model", template={})
        self.assertIn("DSPARK_MODEL_OFFICIAL=/models/drowzeys/model", env)
        self.assertNotIn("/opt/models/models", env)

    def test_compose_maps_model_root_to_container_models_root(self):
        compose = Path("dspark/docker-compose.dspark.yml").read_text(encoding="utf-8")
        self.assertIn("${HF_CACHE:-${HOME}/.cache/huggingface}:/models:ro", compose)
        self.assertNotIn("model_links", compose)


class ApiKeyTests(unittest.TestCase):
    """HTTP 鉴权（config.common.api_key → .env.dspark VLLM_API_KEY → vLLM --api-key）。

    缺陷驱动契约（回归防护）：若 gen_env 不注入 VLLM_API_KEY、或 perf 请求头
    缺失 Authorization Bearer，下列断言必然失败，标志鉴权对接回归。
    """

    def setUp(self):
        self.cfg = {
            "common": {
                "model_lib": "/opt/models",
                "max_request": 6,
                "max_token": 1048576,
                "master_port": 25000,
                "vllm_image": "ghcr.io/anemll/dspark-vllm-gx10:0.1.1",
                "api_url": "http://127.0.0.1:8888/v1/models",
                "api_key": "deepseek",
            },
            "head": {"fabric_ip": "10.100.240.1", "hca": "rocep1s0f0",
                     "ifname": "enp1s0f0np0", "management_ip": "192.168.2.180"},
            "worker": {"fabric_ip": "10.100.240.2", "management_ip": "192.168.2.161",
                       "hca": "rocep1s0f0", "ifname": "enp1s0f0np0"},
        }
        self.k = {
            "api_url": self.cfg["common"]["api_url"],
            "api_key": self.cfg["common"]["api_key"],
            "perf_api_url": "http://192.168.2.180:8888/v1/models",
            "env_file": "/opt/deepseek-flash/dspark/.env.dspark",
        }

    def test_gen_env_injects_vllm_api_key_from_config(self):
        env = program.gen_env(self.cfg, "/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731",
                              template={"VLLM_API_KEY": None})
        self.assertIn("VLLM_API_KEY=deepseek", env)

    def test_gen_env_empty_key_stays_empty(self):
        cfg = dict(self.cfg)
        cfg["common"] = dict(self.cfg["common"], api_key="")
        env = program.gen_env(cfg, "/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731",
                              template={"VLLM_API_KEY": None})
        self.assertIn("VLLM_API_KEY=", env)

    @mock.patch("program.dotask")
    def test_api_healthy_sends_authorization_bearer_with_key(self, dotask):
        dotask.return_value = subprocess.CompletedProcess(["curl"], 0, stdout="", stderr="")

        self.assertTrue(program.api_healthy(self.k))

        self.assertEqual(dotask.call_args.args[0], "curl -fsS --max-time 5")
        self.assertEqual(
            dotask.call_args.args[1],
            ["-H", "Authorization: Bearer deepseek", self.k["api_url"]],
        )

    @mock.patch("program.urllib.request.urlopen")
    def test_sync_sparkdash_api_key_uses_configured_key_for_registered_sparks(self, urlopen):
        registry_response = mock.MagicMock()
        registry_response.__enter__.return_value = registry_response
        registry_response.read.return_value = json.dumps({
            "sparks": [
                {"id": "spark-a", "lanIp": "192.168.2.180", "llmPorts": [8888]},
                {"id": "spark-b", "lanIp": "192.168.2.161", "llmPorts": [8888]},
            ]
        }).encode()
        update_response = mock.MagicMock()
        update_response.__enter__.return_value = update_response
        update_response.status = 200
        urlopen.side_effect = [registry_response, update_response, update_response]

        consts = {
            "api_key": "deepseek",
            "api_url": "http://127.0.0.1:8888/v1/models",
            "sparkdash_url": "http://127.0.0.1:5555",
        }
        cfg = {
            "head": {"management_ip": "192.168.2.180"},
            "worker": {"management_ip": "192.168.2.161"},
        }

        program.sync_sparkdash_api_key(consts, cfg)

        self.assertEqual(urlopen.call_count, 3)
        for call in urlopen.call_args_list[1:]:
            request = call.args[0]
            self.assertEqual(request.get_method(), "PUT")
            self.assertEqual(request.get_header("Content-type"), "application/json")
            self.assertEqual(json.loads(request.data), {"apiKey": "deepseek"})

    @mock.patch("program.urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_sync_sparkdash_is_non_fatal_when_dashboard_is_unavailable(self, _urlopen):
        program.sync_sparkdash_api_key(
            {"api_key": "deepseek", "api_url": "http://127.0.0.1:8888/v1/models",
             "sparkdash_url": "http://127.0.0.1:5555"},
            {"head": {"management_ip": "192.168.2.180"},
             "worker": {"management_ip": "192.168.2.161"}},
        )

    @mock.patch("program.installed_model_name", return_value="deepseek-v4-flash-0731")
    def test_perf_sends_authorization_bearer_with_key(self, _model):
        import urllib.request

        request_args = []

        def fake_urlopen(req, timeout=3600):
            request_args.append(req)
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", req.headers, None)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             mock.patch("program.logtask", side_effect=lambda *a, **k: None):
            try:
                program.cmd_perf(self.k, self.cfg, argparse.Namespace(mode="off", target=10))
            except urllib.error.HTTPError:
                pass
        self.assertTrue(request_args)
        self.assertEqual(request_args[0].get_header("Authorization"), "Bearer deepseek")
        self.assertEqual(request_args[0].full_url, "http://192.168.2.180:8888/tokenize")

    @mock.patch("program.installed_model_name", return_value="deepseek-v4-flash-0731")
    def test_perf_request_sets_thinking_mode_explicitly(self, _model):
        import io
        import json

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.payload

            def __iter__(self):
                return iter(self.payload.splitlines(keepends=True))

        requests = []
        responses = [
            FakeResponse(b'{"count": 9000}'),
            FakeResponse(
                b'data: {"choices":[{"delta":{"content":"VERIFIED"}}]}\n'
                b'data: {"usage":{"prompt_tokens":8299,"completion_tokens":128}}\n'
                b'data: [DONE]\n'
            ),
            FakeResponse(b'{"count": 620000}'),
            FakeResponse(
                b'data: {"choices":[{"delta":{"content":"VERIFIED"}}]}\n'
                b'data: {"usage":{"prompt_tokens":620000,"completion_tokens":128}}\n'
                b'data: [DONE]\n'
            ),
        ]

        def fake_urlopen(request, timeout=3600):
            requests.append((request, timeout))
            return responses.pop(0)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             mock.patch("program.logtask", side_effect=lambda *a, **k: None), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(
                program.cmd_perf(self.k, self.cfg, argparse.Namespace(mode="on", target=10)),
                0,
            )

        stream_body = json.loads(requests[1][0].data)
        self.assertEqual(requests[0][0].full_url, "http://192.168.2.180:8888/tokenize")
        self.assertEqual(requests[1][0].full_url, "http://192.168.2.180:8888/v1/chat/completions")
        self.assertEqual(stream_body["chat_template_kwargs"], {"thinking": True})
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["thinking_mode"], "on")
        self.assertEqual(report["cases"][0]["case"], "short_context_baseline")
        self.assertEqual(report["cases"][1]["case"], "long_context_issue22")
        self.assertEqual(report["cases"][1]["generated_tokens"], 128)
        self.assertEqual(report["verdict"], "pass")

    def test_parser_constants_exposes_api_key(self):
        cfg = {
            "common": {
                "user": "chan", "repo": "/opt/deepseek-flash",
                "runtime_repo": "/opt/deepseek-flash/dspark", "project": "deepseek-v4-flash",
                "container": "deepseek-v4-flash-vllm-dspark-1",
            "model_lib": "/opt/models",
                "default_model": "/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731",
                "vllm_image": "img", "api_url": "http://127.0.0.1:8888/v1/models",
                "master_port": 25000, "api_key": "deepseek",
            },
            "head": {"hostname": "spark-a", "management_ip": "192.168.2.180", "fabric_ip": "10.100.240.1"},
            "worker": {"hostname": "spark-b", "ssh": "chan@spark-b"},
        }
        self.assertEqual(program.parser_constants(cfg)["api_key"], "deepseek")

    def test_compose_passes_api_key_to_vllm_command(self):
        compose = Path(__file__).parents[1].joinpath("dspark", "docker-compose.dspark.yml").read_text()
        self.assertIn('VLLM_API_KEY: "${VLLM_API_KEY:-}"', compose)
        self.assertIn('VLLM_API_KEY_ARGS=(--api-key "$${VLLM_API_KEY}")', compose)
        self.assertIn('"$${VLLM_API_KEY_ARGS[@]}"', compose)

    def test_compose_uses_supported_performance_paths_explicitly(self):
        compose = Path(__file__).parents[1].joinpath("dspark", "docker-compose.dspark.yml").read_text()
        self.assertIn('VLLM_ALLREDUCE_USE_SYMM_MEM: "${VLLM_ALLREDUCE_USE_SYMM_MEM:-0}"', compose)
        self.assertIn('VLLM_USE_NCCL_SYMM_MEM: "${VLLM_USE_NCCL_SYMM_MEM:-0}"', compose)
        self.assertIn('if (( CUDAGRAPH_CAPTURE_SIZE > 32 )); then CUDAGRAPH_CAPTURE_SIZE=32; fi;', compose)
        self.assertIn('--max-cudagraph-capture-size $${CUDAGRAPH_CAPTURE_SIZE}', compose)

    def test_sparse_mla_autotune_covers_two_request_decode_shape(self):
        warmup = Path(__file__).parents[1].joinpath(
            "dspark", "recipe", "overlay", "vllm", "model_executor", "warmup", "kernel_warmup.py"
        ).read_text()
        self.assertIn('min(max_num_seqs, 2)', warmup)
        hotfix = Path(__file__).parents[1].joinpath(
            "dspark", "patches", "hotfix-dsv4-sparse-mla-autotune-shapes.sh"
        ).read_text()
        self.assertIn('sparse MLA autotune now covers 1/2/4 request shapes', hotfix)

    def test_start_script_authenticates_api_probes_and_fails_strict_hotfix(self):
        start = Path(__file__).parents[1].joinpath(
            "dspark", "start-deepseek-v4-flash-dspark.sh"
        ).read_text()
        self.assertIn('Authorization: Bearer ${VLLM_API_KEY}', start)
        self.assertIn('if api_curl "$API_URL"', start)
        self.assertIn('api_curl "$CHAT_URL"', start)
        self.assertIn('docker exec "${PROJECT_NAME}-vllm-dspark-1" bash "/tmp/$_hf"', start)
        self.assertIn('docker exec "${PROJECT_NAME}-vllm-dspark-1" bash "/tmp/$_hf" || true', start)
        self.assertIn('if [ "$_hf" = "hotfix-dsv4-sparse-mla-autotune-shapes.sh" ]; then', start)


if __name__ == "__main__":
    unittest.main()
