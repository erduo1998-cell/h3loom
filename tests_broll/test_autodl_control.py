from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from broll_video.autodl.control import (
    AutoDLControlClient,
    AutoDLControlError,
    AutoDLControlPolicy,
    AutoDLInstanceStatus,
    IndeterminatePowerRequest,
)
from broll_video.autodl.credentials import (
    AutoDLCredentialError,
    AutoDLCredentials,
    install_secure_autodl_credentials,
    write_secure_autodl_credentials,
)
from broll_video.autodl.comfy import AutoDLComfyClient
from broll_video.autodl.readiness import (
    AutoDLReadinessError,
    GoldenStackPolicy,
    check_comfy_ready,
    validate_golden_runtime_evidence,
    validate_golden_stack,
    validate_daily_readiness,
)
from broll_video.autodl.pricing import AutoDLPricingCatalog, AutoDLPricingError
from broll_video.autodl.runtime import AutoDLRuntime, AutoDLRuntimeError, DEFAULT_PROFILES
from broll_video.autodl.runtime import AutoDLPromptRuntime
from broll_video.autodl.cli import _completed_results
from broll_video.autodl.service import BrollAutoDLService
from broll_video.autodl.workflow import AutoDLWorkflowCompiler
from broll_video.autodl.ssh import (
    AutoDLSSHClient,
    AutoDLSSHError,
    parse_ssh_connection_command,
)
from broll_video.h3.models import H3Request, MediaAsset
from broll_video.task import BrollTaskStore


ROOT = Path(__file__).parents[1]


class FakeHTTP:
    def __init__(self, responses: list[tuple[int, bytes] | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body))
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def response(data, request_id="req-test") -> tuple[int, bytes]:
    return 200, json.dumps({"code": "Success", "data": data, "msg": "", "request_id": request_id}).encode()


def snapshot(**overrides):
    value = {
        "snapshot_gpu_alias_name": "NVIDIA RTX PRO 6000",
        "payg_price": 5980,
        "proxy_host": "connect.westd.seetacloud.com",
        "ssh_port": 33235,
    }
    value.update(overrides)
    return value


def instance_list(**overrides):
    row = {"uuid": "pro-test", "status": "shutdown", "gpu_spec_uuid": "pro6000-p"}
    row.update(overrides)
    return {"list": [row]}


class CredentialsTests(unittest.TestCase):
    def test_ssh_only_credentials_round_trip_without_developer_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            credentials = AutoDLCredentials._validated_ssh(
                ssh_user="root",
                ssh_password="private-password",
                ssh_host="connect.westd.seetacloud.com",
                ssh_port=26979,
                ssh_host_key_sha256="SHA256:approved",
            )
            target = write_secure_autodl_credentials(directory, credentials)
            loaded = AutoDLCredentials.load(directory, environ={})
            self.assertEqual("ssh", loaded.connection_mode)
            self.assertIsNone(loaded.access_token)
            self.assertEqual(26979, loaded.ssh_port)
            self.assertNotIn("private-password", repr(loaded))
            self.assertEqual(0o600, target.stat().st_mode & 0o777)

    def test_auto_dl_ssh_command_is_the_only_connection_input_user_needs(self) -> None:
        self.assertEqual(
            parse_ssh_connection_command(
                r"ssh -p 26979 root\@connect.westd.seetacloud.com"
            ),
            ("root", "connect.westd.seetacloud.com", 26979),
        )

    def test_auto_dl_ssh_command_rejects_non_connection_shell_content(self) -> None:
        with self.assertRaises(AutoDLSSHError):
            parse_ssh_connection_command(
                "ssh -p 26979 root@connect.westd.seetacloud.com uptime"
            )

    def test_env_pair_wins_without_filesystem_access(self) -> None:
        credentials = AutoDLCredentials.load(
            "/missing", environ={
                "AUTODL_ACCESS_TOKEN": "token-value",
                "AUTODL_INSTANCE_UUID": "pro-test",
                "AUTODL_SSH_HOST_KEY_SHA256": "SHA256:approved",
            }
        )
        self.assertEqual(credentials.instance_uuid, "pro-test")
        self.assertEqual(credentials.ssh_host_key_sha256, "SHA256:approved")

    def test_env_pair_must_be_complete(self) -> None:
        with self.assertRaisesRegex(AutoDLCredentialError, "set together"):
            AutoDLCredentials.load(environ={"AUTODL_ACCESS_TOKEN": "token-value"})

    def test_file_requires_exact_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autodl.local.json"
            path.write_text('{"access_token":"token-value","instance_uuid":"pro-test"}')
            path.chmod(0o640)
            with self.assertRaises(AutoDLCredentialError):
                AutoDLCredentials.load(secure_config=path, environ={})
            path.chmod(0o600)
            self.assertEqual(AutoDLCredentials.load(secure_config=path, environ={}).instance_uuid, "pro-test")

    def test_interactive_installer_writes_owner_only_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = install_secure_autodl_credentials(
                directory,
                token_reader=lambda _: "token-value",
                instance_reader=lambda _: "pro-test",
                host_key_reader=lambda _: "SHA256:approved",
            )
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            loaded = AutoDLCredentials.load(secure_config=target, environ={})
            self.assertEqual(loaded.ssh_host_key_sha256, "SHA256:approved")


class ControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = AutoDLControlPolicy.load(ROOT / "config/autodl-control.json")
        self.credentials = AutoDLCredentials("never-render-token", "pro-test")

    def client(self, responses):
        http = FakeHTTP(responses)
        return AutoDLControlClient(self.credentials, self.policy, http=http), http

    def test_status_uses_get_query_and_receipt_never_has_token(self) -> None:
        client, http = self.client([response("running")])
        status = client.status()
        method, url, headers, body = http.calls[0]
        self.assertEqual(method, "GET")
        self.assertIn("instance_uuid=pro-test", url)
        self.assertIsNone(body)
        self.assertEqual(headers["Authorization"], "never-render-token")
        self.assertNotIn("never-render-token", repr(status))

    def test_resolves_dynamic_ssh_target_from_authenticated_snapshot(self) -> None:
        client, http = self.client([response(snapshot(ssh_port=30123))])
        target = client.resolve_ssh_endpoint()
        self.assertEqual((target.host, target.port), ("connect.westd.seetacloud.com", 30123))
        self.assertEqual(http.calls[0][0], "GET")

    def test_snapshot_password_is_ephemeral_and_redacted(self) -> None:
        client, _ = self.client([response(snapshot(root_password="secret"))])
        access = client.resolve_ssh_access()
        self.assertEqual(access.password, "secret")
        self.assertNotIn("secret", repr(access))

    def test_untrusted_snapshot_host_fails_closed(self) -> None:
        client, _ = self.client([response(snapshot(proxy_host="attacker.example"))])
        with self.assertRaisesRegex(AutoDLControlError, "untrusted SSH host"):
            client.resolve_ssh_endpoint()

    def test_power_on_reuses_verified_snapshot_and_posts_exact_payload(self) -> None:
        client, http = self.client([
            response(instance_list()), response(snapshot()), response("shutdown"), response(None, "power-on"),
        ])
        result = client.power_on()
        self.assertEqual(result.request_id, "power-on")
        self.assertEqual([call[0] for call in http.calls], ["POST", "GET", "GET", "POST"])
        self.assertEqual(json.loads(http.calls[-1][3]), {"instance_uuid": "pro-test", "payload": "gpu"})

    def test_power_on_accepts_positive_live_price_instead_of_stale_config_equality(self) -> None:
        client, http = self.client([
            response(instance_list()), response(snapshot(payg_price=5981)),
            response("shutdown"), response(None, "power-on"),
        ])
        self.assertEqual("power-on", client.power_on().request_id)
        self.assertEqual([call[0] for call in http.calls], ["POST", "GET", "GET", "POST"])

    def test_power_off_uncertain_post_is_not_retried(self) -> None:
        client, http = self.client([response("running"), TimeoutError("network")])
        with self.assertRaises(IndeterminatePowerRequest):
            client.power_off()
        self.assertEqual([call[0] for call in http.calls], ["GET", "POST"])

    def test_power_off_does_not_post_if_status_is_terminal(self) -> None:
        client, http = self.client([response("released")])
        self.assertTrue(client.power_off().stopped)
        self.assertEqual([call[0] for call in http.calls], ["GET"])


class ReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = GoldenStackPolicy.load(ROOT / "config/autodl-stack-fingerprint.json")
        self.endpoint = type("Endpoint", (), {"host": "connect.westd.seetacloud.com", "port": 33235, "instance_uuid": "pro-test"})()
        self.system_stats = {
            "system": {"comfyui_version": "0.33.1", "required_frontend_version": "1.48.7"},
            "devices": [{"name": "cuda:0 NVIDIA RTX PRO 6000 Blackwell Server Edition : cudaMallocAsync", "vram_total": 101975851008}],
        }

    def test_golden_stack_fingerprint_passes_without_model_file_hashes(self) -> None:
        evidence = validate_golden_stack(self.system_stats, self.policy)
        self.assertEqual(evidence.fingerprint_sha256, self.policy.expected_fingerprint)

    def test_golden_stack_fingerprint_mismatch_fails_closed(self) -> None:
        bad = dict(self.system_stats)
        bad["system"] = {**self.system_stats["system"], "comfyui_version": "0.34.0"}
        with self.assertRaisesRegex(AutoDLReadinessError, "fingerprint mismatch"):
            validate_golden_stack(bad, self.policy)

    def test_daily_readiness_checks_gpu_without_reauditing_software_versions(self) -> None:
        changed = dict(self.system_stats)
        changed["system"] = {"comfyui_version": "changed-after-first-verify"}
        evidence = validate_daily_readiness(changed, self.policy)
        self.assertEqual(self.policy.expected_fingerprint, evidence.fingerprint_sha256)

    def test_golden_runtime_receipt_is_small_and_fail_closed(self) -> None:
        self.assertEqual(
            validate_golden_runtime_evidence(self.policy.golden_runtime_evidence, self.policy),
            self.policy.golden_runtime_evidence_fingerprint,
        )
        bad = dict(self.policy.golden_runtime_evidence)
        bad["torch_version"] = "changed"
        with self.assertRaisesRegex(AutoDLReadinessError, "runtime evidence mismatch"):
            validate_golden_runtime_evidence(bad, self.policy)

    def test_readiness_uses_key_pinned_ssh_and_remote_loopback_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            known_hosts = Path(directory) / "known_hosts"
            known_hosts.write_text("known key\n")
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(self.system_stats), stderr="")
            stats = check_comfy_ready(self.endpoint, known_hosts=known_hosts, runner=runner)
            self.assertEqual(stats["system"]["comfyui_version"], "0.33.1")
            command = calls[0]
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("HostKeyAlias=autodl-pro-test", command)
            self.assertIn("http://127.0.0.1:8188/system_stats", command[-1])

    def test_readiness_refuses_unpinned_or_failed_ssh(self) -> None:
        with self.assertRaisesRegex(AutoDLReadinessError, "known_hosts"):
            check_comfy_ready(self.endpoint, known_hosts=Path("/not-present"))


class PricingTests(unittest.TestCase):
    def test_live_price_and_conservative_quote(self) -> None:
        cached = AutoDLPricingCatalog.load(ROOT / "config/autodl-pricing.json")
        catalog = cached.with_live_payg_milli(6123)
        self.assertEqual("6.123", str(catalog.hourly_rate_cny))
        self.assertIn("authenticated_snapshot_payg", catalog.source_reference)
        self.assertGreater(catalog.quote("fast"), 0)
        with self.assertRaises(AutoDLPricingError):
            cached.with_live_payg_milli(0)

    def test_every_approved_production_profile_has_a_quote(self) -> None:
        catalog = AutoDLPricingCatalog.load(ROOT / "config/autodl-pricing.json")
        for profile in DEFAULT_PROFILES:
            self.assertGreater(catalog.quote(profile), 0)
        catalog.validate_rtx_canary(
            "4K", {"passed": True, "applicable": True, "fps": 24}
        )


class SSHTests(unittest.TestCase):
    def test_ssh_client_requires_approved_fingerprint_without_exposing_password(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            known_hosts = Path(directory) / "known_hosts"
            known_hosts.write_text("[connect.westd.seetacloud.com]:33235 ssh-ed25519 AAAA\n")
            endpoint = type("Endpoint", (), {"host": "connect.westd.seetacloud.com", "port": 33235, "instance_uuid": "pro-test"})()
            credentials = AutoDLCredentials("token", "pro-test", ssh_password="secret", ssh_host_key_sha256="SHA256:approved")
            client = AutoDLSSHClient(endpoint, credentials, known_hosts=known_hosts)
            with self.assertRaisesRegex(AutoDLSSHError, "host key"):
                client.run(["true"])

    def test_remote_python_is_sent_as_one_shell_quoted_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            known_hosts = Path(directory) / "known_hosts"
            known_hosts.write_text("key\n")
            endpoint = type("Endpoint", (), {"host": "connect.westd.seetacloud.com", "port": 33235, "instance_uuid": "pro-test"})()
            credentials = AutoDLCredentials(
                "token", "pro-test", ssh_host_key_sha256="SHA256:approved"
            )
            client = AutoDLSSHClient(endpoint, credentials, known_hosts=known_hosts)
            remote = ["python3", "-c", "print('a b'); print('done')"]
            self.assertEqual(client._ssh_command(remote)[-1], shlex.join(remote))
            self.assertIn("HostKeyAlias=autodl-pro-test", client._ssh_command(remote))

    def test_password_transport_does_not_enable_batch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            known_hosts = Path(directory) / "known_hosts"
            known_hosts.write_text("[connect.westd.seetacloud.com]:33235 ssh-ed25519 AAAA\n")
            endpoint = type("Endpoint", (), {"host": "connect.westd.seetacloud.com", "port": 33235, "instance_uuid": "pro-test"})()
            password_client = AutoDLSSHClient(endpoint, AutoDLCredentials("token", "pro-test", ssh_password="secret", ssh_host_key_sha256="SHA256:approved"), known_hosts=known_hosts)
            key_client = AutoDLSSHClient(endpoint, AutoDLCredentials("token", "pro-test", ssh_host_key_sha256="SHA256:approved"), known_hosts=known_hosts)
            self.assertNotIn("BatchMode=yes", password_client._ssh_command(["true"]))
            self.assertIn("PreferredAuthentications=password,keyboard-interactive", password_client._ssh_command(["true"]))
            self.assertIn("BatchMode=yes", key_client._ssh_command(["true"]))


class ComfySSHOnlyTests(unittest.TestCase):
    def test_video_recovery_copies_the_exact_persistent_output(self) -> None:
        class SSH:
            endpoint = type("Endpoint", (), {"instance_uuid": "ssh-test"})()

            def __init__(self):
                self.calls = []

            def copy_from(self, remote, destination, **kwargs):
                self.calls.append((remote, Path(destination), kwargs))
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                Path(destination).write_bytes(b"video")
                return Path(destination)

        with tempfile.TemporaryDirectory() as directory:
            ssh = SSH()
            destination = Path(directory) / "clip.mp4"
            result = AutoDLComfyClient(ssh).download_output_to(
                object(),
                {
                    "filename": "clip_00001_.mp4",
                    "subfolder": "video",
                    "type": "output",
                },
                destination,
            )
            self.assertEqual(destination, result)
            self.assertEqual(
                "/root/autodl-tmp/h3-stack/ComfyUI/output/video/clip_00001_.mp4",
                ssh.calls[0][0],
            )

    def test_daily_system_stats_reuses_the_launch_scripts_curl_probe(self) -> None:
        class SSH:
            endpoint = type("Endpoint", (), {"instance_uuid": "ssh-test"})()

            def __init__(self):
                self.calls = []

            def run(self, command, **kwargs):
                self.calls.append((command, kwargs))
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"devices": [{"name": "gpu"}]}),
                    stderr="",
                )

        ssh = SSH()
        value = AutoDLComfyClient(ssh).system_stats()
        self.assertEqual("gpu", value["devices"][0]["name"])
        self.assertEqual("/usr/bin/curl", ssh.calls[0][0][0])
        self.assertIn("http://127.0.0.1:8188/system_stats", ssh.calls[0][0])

    def test_ssh_only_shutdown_is_verified_when_remote_becomes_unreachable(self) -> None:
        class SSH:
            endpoint = type("Endpoint", (), {"instance_uuid": "ssh-test"})()

            def __init__(self):
                self.calls = 0

            def run(self, command, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                raise AutoDLSSHError("unreachable")

        receipt = AutoDLComfyClient(SSH()).shutdown_and_wait(
            timeout=0.1, poll_interval=0
        )
        self.assertTrue(receipt["shutdown_verified"])
        self.assertEqual(
            "remote_os_shutdown_ssh_unreachable", receipt["terminal_status"]
        )


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.media = Path(self.temporary.name) / "approved-board.png"
        self.media.write_bytes(b"self-contained approved storyboard fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_runtime_accepts_normal_profile_without_live_object_info(self) -> None:
        stack = validate_golden_stack(
            {
                "system": {"comfyui_version": "0.33.1", "required_frontend_version": "1.48.7"},
                "devices": [{"name": "cuda:0 NVIDIA RTX PRO 6000 Blackwell Server Edition : cudaMallocAsync", "vram_total": 101975851008}],
            }, GoldenStackPolicy.load(ROOT / "config/autodl-stack-fingerprint.json")
        )
        request = H3Request(
            prompt="test", duration=4, ratio="4:3", resolution="4K", provider_profile="fast",
            media=(MediaAsset(source=str(self.media), role="reference_image"),),
        )
        evidence = AutoDLRuntime().pre_submit_gate(request, stack_fingerprint=stack)
        self.assertEqual(evidence.environment_gate, "golden_stack_readiness_passed")
        self.assertTrue(evidence.compiled.uploads[0].remote_name.startswith("autodl/"))
        self.assertTrue(evidence.compiled.output_prefix.startswith("video/autodl_"))
        self.assertEqual(
            evidence.compiled.output_prefix,
            evidence.compiled.prompt["92"]["inputs"]["filename_prefix"],
        )

    def test_fast_compiles_the_official_six_section_ref2va_prompt(self) -> None:
        request = H3Request(
            prompt="A paper mechanism opens.",
            duration=4,
            ratio="4:3",
            resolution="4K",
            provider_profile="fast",
            media=(
                MediaAsset(
                    source=str(self.media),
                    role="reference_image",
                    semantic_role="keyframe",
                    prompt_label="approved opening state",
                    must_preserve=("paper material", "folded geometry"),
                    may_change=("hinge angle",),
                ),
            ),
        )
        effective = AutoDLWorkflowCompiler().compile(request).prompt["136"]["inputs"][
            "prompt"
        ]
        sections = (
            "subject_definitions:",
            "summary:",
            "retention_analysis:",
            "detailed_description:",
            "overall_soundscape:",
            "non_diegetic_music:",
        )
        section_offsets = [effective.index(section) for section in sections]
        self.assertEqual(sorted(section_offsets), section_offsets)
        self.assertIn("<Picture 1> is approved opening state", effective)
        self.assertIn("Preserve paper material, folded geometry", effective)
        self.assertIn("[Shot 1] A paper mechanism opens.", effective)
        self.assertIn("No dialogue, narration, voice, singing", effective)
        self.assertIn("Do not infer speech from text or reference images", effective)
        self.assertNotIn("Only the dialogue and synchronized", effective)
        self.assertTrue(effective.endswith("non_diegetic_music:\nN/A"))

    def test_precision_compiles_the_official_three_section_fl2va_prompt(self) -> None:
        request = H3Request(
            prompt="A paper mechanism opens through three approved states.",
            duration=4,
            ratio="4:3",
            resolution="4K",
            provider_profile="precision_keyframes",
            media=tuple(
                MediaAsset(source=str(self.media), role="reference_image")
                for _ in range(3)
            ),
        )
        effective = AutoDLWorkflowCompiler().compile(request).prompt["136"]["inputs"][
            "prompt"
        ]
        self.assertTrue(
            effective.startswith(
                "How the reference pictures align with the target video —"
            )
        )
        self.assertIn(
            "Picture 1 aligns with the 0.00-second mark", effective
        )
        self.assertIn(
            "Picture 2 aligns with the 2.00-second mark", effective
        )
        self.assertIn(
            "Picture 3 aligns with the 4.00-second mark", effective
        )
        self.assertNotIn("KEYFRAME ALIGNMENT:", effective)
        sections = (
            "integrated_multimodal_description:",
            "overall_soundscape:",
            "non_diegetic_music:",
        )
        section_offsets = [effective.index(section) for section in sections]
        self.assertEqual(sorted(section_offsets), section_offsets)
        self.assertIn("A paper mechanism opens through three approved states.", effective)
        self.assertIn("No dialogue, narration, voice, singing", effective)
        self.assertIn("Do not infer speech from text or reference images", effective)
        self.assertNotIn("Only the dialogue and synchronized", effective)
        self.assertTrue(effective.endswith("non_diegetic_music: N/A"))

    def test_explicit_scripted_music_policy_is_fingerprinted_and_removes_default_guard(self) -> None:
        base = H3Request(
            prompt="A paper mechanism opens with a scripted musical cue.",
            duration=4,
            ratio="4:3",
            resolution="4K",
            provider_profile="fast",
            media=(MediaAsset(source=str(self.media), role="reference_image"),),
        )
        sfx = AutoDLWorkflowCompiler().compile(base)
        music = AutoDLWorkflowCompiler().compile(
            H3Request(**{**base.__dict__, "audio_policy": "scripted_music"})
        )
        music_prompt = music.prompt["136"]["inputs"]["prompt"]
        self.assertNotIn("non_diegetic_music:\nN/A", music_prompt)
        self.assertIn("Use only the non-diegetic music explicitly scripted", music_prompt)
        self.assertNotEqual(sfx.fingerprint, music.fingerprint)

    def test_runtime_blocks_m5_and_m4(self) -> None:
        stack = validate_golden_stack(
            {"system": {"comfyui_version": "0.33.1", "required_frontend_version": "1.48.7"}, "devices": [{"name": "cuda:0 NVIDIA RTX PRO 6000 Blackwell Server Edition : cudaMallocAsync", "vram_total": 101975851008}]},
            GoldenStackPolicy.load(ROOT / "config/autodl-stack-fingerprint.json"),
        )
        request = H3Request(prompt="test", duration=4, ratio="4:3", media=(MediaAsset(source=str(self.media), role="reference_image"),), provider_profile="fast")
        with self.assertRaisesRegex(AutoDLRuntimeError, "M4"):
            AutoDLRuntime().pre_submit_gate(request, stack_fingerprint=stack, m4_enabled=True)

    def test_provider_fingerprint_binds_the_golden_stack(self) -> None:
        policy = GoldenStackPolicy.load(ROOT / "config/autodl-stack-fingerprint.json")
        stack = validate_golden_stack(
            {
                "system": {"comfyui_version": "0.33.1", "required_frontend_version": "1.48.7"},
                "devices": [{"name": "cuda:0 NVIDIA RTX PRO 6000 Blackwell Server Edition : cudaMallocAsync", "vram_total": 101975851008}],
            },
            policy,
        )
        changed = type(stack)(
            stack.fingerprint_version,
            "f" * 64,
            stack.golden_runtime_evidence_sha256,
            stack.comfyui_version,
            stack.required_frontend_version,
            stack.gpu_name,
            stack.vram_total_bytes,
        )
        request = H3Request(
            prompt="test", duration=4, ratio="4:3", resolution="4K",
            provider_profile="fast",
            media=(MediaAsset(source=str(self.media), role="reference_image"),),
        )
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = AutoDLPromptRuntime(first, object(), stack_fingerprint=stack)
            right = AutoDLPromptRuntime(second, object(), stack_fingerprint=changed)
            compiled = left.compiler.compile(request)
            self.assertNotEqual(
                left.production_fingerprint(compiled), right.production_fingerprint(compiled)
            )

        changed_runtime = type(stack)(
            stack.fingerprint_version,
            stack.fingerprint_sha256,
            "e" * 64,
            stack.comfyui_version,
            stack.required_frontend_version,
            stack.gpu_name,
            stack.vram_total_bytes,
        )
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = AutoDLPromptRuntime(first, object(), stack_fingerprint=stack)
            right = AutoDLPromptRuntime(second, object(), stack_fingerprint=changed_runtime)
            compiled = left.compiler.compile(request)
            self.assertNotEqual(
                left.production_fingerprint(compiled), right.production_fingerprint(compiled)
            )


class AutoDLServiceLifecycleTests(unittest.TestCase):
    def _task(self, root: Path, *, delivered: bool = True):
        source = root / "source.srt"
        source.write_text("1\n00:00:00,000 --> 00:00:04,000\n测试\n", encoding="utf-8")
        store = BrollTaskStore(root / "work/tasks")
        task = store.create(
            name="autodl-lifecycle",
            source_srt=source,
            ratio="16:9",
            execution_mode="authorized",
            production_contract=None,
        )
        task["budget"]["committed"] = 2.0
        store.save(task)
        directory = store.directory(task["task_id"])
        if delivered:
            (directory / "delivery-manifest.json").write_text(
                json.dumps({"clips": []}), encoding="utf-8"
            )
        service = BrollAutoDLService(
            store,
            AutoDLPricingCatalog.load(ROOT / "config/autodl-pricing.json"),
            object(),
            project_root=root,
            golden_stack=GoldenStackPolicy.load(
                ROOT / "config/autodl-stack-fingerprint.json"
            ),
        )
        return store, task, service

    def test_ssh_only_service_delegates_shutdown_to_remote_os_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []

            class SSHOnlyClient:
                control = None

                def shutdown_and_wait(self, *, timeout, poll_interval):
                    calls.append((timeout, poll_interval))
                    return {
                        "shutdown_verified": True,
                        "terminal_status": "remote_os_shutdown_ssh_unreachable",
                    }

            store = BrollTaskStore(root / "work/tasks")
            service = BrollAutoDLService(
                store,
                AutoDLPricingCatalog.load(ROOT / "config/autodl-pricing.json"),
                SSHOnlyClient(),
                project_root=root,
                golden_stack=GoldenStackPolicy.load(
                    ROOT / "config/autodl-stack-fingerprint.json"
                ),
            )
            receipt = service.shutdown(timeout=12.0, poll_interval=0.5)
            self.assertEqual(calls, [(12.0, 0.5)])
            self.assertTrue(receipt["shutdown_verified"])
            self.assertEqual(
                receipt["terminal_status"], "remote_os_shutdown_ssh_unreachable"
            )

    def test_incomplete_delivery_manifest_is_not_a_completed_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, task, service = self._task(root)
            self.assertIsNone(service._completed_results(task["task_id"]))

    def test_incomplete_live_run_never_auto_shutdowns_the_acquired_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, task, service = self._task(root, delivered=False)
            calls = []

            class Client:
                def start(self):
                    calls.append("start")

                def session(self):
                    calls.append("tunnel")
                    return nullcontext(self)

                def instance(self):
                    calls.append("instance")
                    return type("Info", (), {"instance_id": "test-instance"})()

                def shutdown_and_wait(self):
                    calls.append("shutdown")
                    return {"shutdown_verified": True}

            service.client = Client()
            service._load_live_batch = lambda _task_id: ({}, [{}])  # type: ignore[method-assign]

            def fail_after_submit(*_args, **_kwargs):
                raise RuntimeError("local download parsing failed")

            service._run_item = fail_after_submit  # type: ignore[method-assign]
            with self.assertRaisesRegex(RuntimeError, "download parsing"):
                service.run_batch(task["task_id"])
            self.assertEqual(calls, ["start", "tunnel", "instance"])

    def test_completed_results_are_read_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, task, _ = self._task(root)
            path = store.directory(task["task_id"]) / "h3-requests/b01/attempt-001/result.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"prompt_id":"existing"}', encoding="utf-8")
            self.assertIsNone(_completed_results(root, task["task_id"]))
