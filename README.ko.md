<div align="center">

# H3Loom

### 클라우드 모델을 나만의 영상 제작 스튜디오로.

[简体中文](README.md) · [English](README.en.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · **한국어**

[![Python](docs/images/badges/python.svg)](pyproject.toml)
[![Agent Skills](docs/images/badges/skills.svg)](.agents/skills/srt-broll-producer/SKILL.md)
[![Runtime](docs/images/badges/runtime.svg)](docs/autodl-production.md)
[![Status](docs/images/badges/status.svg)](https://github.com/erduo1998-cell/h3loom/releases/tag/v0.2.0rc1)
[![License: Apache-2.0](docs/images/badges/license.svg)](LICENSE)

**직접 운영하는 클라우드 · 지속적인 생성 실험 · 나만의 영상 스타일**

</div>

전용 클라우드 환경에 MiniMax H3를 배포하고, 실험과 제작, 결과 검토를 반복하면서 일관된 참고 이미지와 촬영 표현, 생성 노하우를 쌓아갑니다. 이렇게 축적한 경험으로 계속 재사용할 수 있는 자신만의 스타일을 만듭니다.

**AI 영상을 꾸준히 제작하며 실전을 통해 스타일을 다듬고 싶은 크리에이터를 위한 프로젝트입니다.** 현재 주 작업 흐름은 말하는 영상의 SRT 자막을 독립적인 4K B-roll 소재로 바꾸는 것입니다. Agent가 샷 설계, 스토리보드 제작, 클라우드 실행을 맡습니다.

> H3Loom은 독립적인 MiniMax H3 클라우드 제작 도구입니다. 첫 공개 버전은 **v0.2.0rc1**이며, 자체 코드와 세 Skill은 [Apache-2.0](LICENSE)을 따릅니다. 모델에는 별도의 지역 및 상업적 이용 조건이 있으며 대한민국은 허용 지역에서 제외됩니다. 한국어 문서는 한국 내 이용 허가를 의미하지 않습니다. [외부 라이선스](THIRD_PARTY_NOTICES.md)를 확인하세요. 새 GPU 설치와 전체 영상 생성 과정은 실기기 검증이 남아 있습니다. [출시 검증](docs/release-readiness.md)을 참고하세요.


### 24초 프로젝트 소개 · 코드로 제작

[![24초 프로젝트 소개 · 코드로 제작](docs/media/h3loom-intro-poster.png)](docs/media/h3loom-intro.mp4)

[MP4 재생](docs/media/h3loom-intro.mp4) · [소스 및 빌드 방법](media/intro/README.md)

로컬 3D 렌더링, 애니메이션, 합성 음향으로 제작했습니다. 은색 모듈은 런타임의 개념 표현이며 실제 하드웨어나 H3 생성 샘플이 아닙니다.


![클라우드 배포, 생성 실험, 사람의 결과 검토, 개인 스타일 축적을 보여 주는 순환도](docs/images/style-loop.png)

<p align="center"><sub>01 전용 클라우드 환경 → 02 반복 생성 실험 → 03 선별과 결과 검토 → 04 개인 스타일을 축적하고 다음 제작에 반영</sub></p>

## 🎯 이 프로젝트를 만든 이유

한 번 생성하면 영상 한 편을 얻지만, 자신만의 제작 방법은 꾸준히 만들면서 쌓입니다. 직접 임대한 서버에 모델을 배포하면 같은 환경에서 피사체, 질감, 색상, 조명, 샷 크기와 움직임을 반복해서 실험할 수 있습니다. 효과가 있었던 방법을 남겨두면 무작정 시도하는 횟수를 조금씩 줄일 수 있습니다.

실제로 축적하는 자산은 다음 세 가지입니다.

| 쌓이는 자산 | 다음 제작에 주는 도움 |
| --- | --- |
| **나만의 시각 참고 자료** | 캐릭터, 질감, 색상, 조명을 일관되게 유지해 여러 영상의 스타일을 연결합니다. |
| **나만의 샷 설계·프롬프트 경험** | 어떤 장면, 동작, 샷 조합이 원하는 결과를 얻는 데 유리한지 파악합니다. |
| **나만의 제작·선별 절차** | 스토리보드를 먼저 확인한 뒤 영상을 생성하고, 문제를 기록해 다음 제작에 개선 사항을 반영합니다. |

목표는 결과의 일관성을 높이고, 실제로 쓸 수 있는 소재를 얻는 비율을 점차 높이는 것입니다. **이 프로젝트에는 모델 학습이나 파인튜닝이 포함되어 있지 않습니다. 생성 횟수를 늘린다고 모델 가중치가 자동으로 바뀌지는 않습니다.** 개선은 사용자와 Agent가 쌓은 참고 자료, 콘티, 프롬프트, 결과 검토 경험에서 나옵니다.

## 🎬 말하는 영상의 자막에서 독립적인 영상 소재까지

![샷 설계, 4컷 스토리보드, 클라우드 생성으로 이어지는 3단계 작업 흐름](docs/images/workflow-v2.png)

<p align="center"><sub>01 샷 설계 → 02 스토리보드 확인 → 03 클라우드 생성 및 다운로드. 위의 소개 이미지 두 장은 모두 AI로 생성한 개념도이며, H3로 실제 제작한 영상의 예시가 아닙니다.</sub></p>

| 단계 | 사용자와 Agent가 함께 하는 일 | 해당 Skill |
| --- | --- | --- |
| **01 · 샷 설계** | SRT 전체와 콘텐츠 스타일 참고 자료, 원본 토크 영상과의 연결을 위한 참고 자료를 읽고 화면 구성, 삽입 구간, 촬영 리듬을 정합니다. | [srt-broll-producer](.agents/skills/srt-broll-producer/SKILL.md) |
| **02 · 스토리보드 확인** | 보드마다 정확히 4컷을 구성합니다. 먼저 샘플 1~2개를 확인한 후 전체를 제작하고, 각 단위마다 불필요한 표시가 없는 앵커 이미지 3~5장을 고릅니다. | [broll-storyboard-producer](.agents/skills/broll-storyboard-producer/SKILL.md) |
| **03 · 생성 및 수령** | 확인된 스토리보드를 기준으로 요청을 구성하고, AutoDL에서 생성·다운로드·중단 작업 재개를 수행합니다. 마지막으로 사람이 영상을 검토합니다. | [h3-video-runtime](.agents/skills/h3-video-runtime/SKILL.md) |

시각적 기준과 샷 계획, 샘플, 전체 콘티는 각각 사용자의 확인을 거칩니다. 승인 후 예산에 따라 실행합니다. 기본 결과물은 한 편당 **4~15초 길이의 독립적인 4K 소재**이며, 완성된 토크 영상으로 자동 편집하지는 않습니다. 2단계에는 Codex 호스트의 `imagegen` 이미지 생성 기능이 필요합니다.

[전체 3단계 작업 흐름 보기](docs/three-stage-workflow.md) · [설치 및 운영 안내서 보기](docs/getting-started.md)

## 💰 실제 비용: GPU 사용료 + 장기 저장 비용

아래 내용은 **제작자가 제공한 실제 제작 경험과 예산 추정치이며, 2026년 9월 7일에 기록했습니다.** 플랫폼의 실시간 공통 요금이 아니며, 모든 작업에서 같은 비용이 나온다는 보장도 아닙니다. 금액은 모두 중국 위안화(CNY)입니다.

| 항목 | 제작자의 실측 경험 / 현재 적용한 기준 | 예산을 잡을 때의 해석 |
| --- | --- | --- |
| **영상 생성 비용** | 약 **CNY 0.10 / 초** | 채택하지 않은 후보를 포함해 생성한 모든 영상의 총길이를 기준으로 계산한 경험값입니다. 최종 선택한 소재의 초당 비용은 이보다 높을 수 있습니다. 장기 저장 비용은 별도입니다. |
| **GPU 서버** | 약 **CNY 6 / 시간** | 실제 서버 점유 시간을 기준으로 계산합니다. 초기 설정, 대기, 재시도도 서버 가동 시간에 포함됩니다. |
| **제작 1회 사례** | **20개 샷, 약 2시간. 제작자가 기록한 비용은 약 CNY 10** | CNY 6 × 2시간으로 예산을 잡으면 **약 CNY 12**가 필요합니다. 실측 경험에 대한 설명과 시간당 요금으로 계산한 추정치를 구분해 기록했습니다. |
| **자료 장기 보관** | 약 **CNY 3 / 일**, 30일 기준 **CNY 90 / 월** | 클라우드에 모델과 자료를 유지하는 고정 비용으로, 월 예산에 별도로 반영해야 합니다. |

**자료를 한 달 내내 보관하면서 위의 20개 샷 작업을 한 번만 한다면, 예산 예시는 CNY 90 + CNY 12 ≈ CNY 102입니다.** 명시된 저장 규모와 30일, GPU 사용 2시간을 기준으로 계산한 예시일 뿐 패키지 가격이 아닙니다. 모든 비용을 '초당 CNY 0.10'에 포함한 것도 아닙니다.

총지출에는 이용하는 이미지 생성 서비스, Agent 구독, 기타 추가 서비스 비용도 고려해야 합니다. GPU를 종료한 뒤에도 플랫폼에 저장 공간이 유지되고 요금이 부과되는지 별도로 확인하세요. 생성을 멈췄다고 모든 비용이 0이 되는 것은 아닙니다. 청구 근거가 충분하지 않으면 프로그램은 실제 비용을 확인 대기 상태로 남겨두며, 추정치를 이미 결제된 청구 금액처럼 취급하지 않습니다.

## 🚀 시작 전에 준비할 것

- **로컬 환경**: 이미지 생성 기능이 내장된 Codex, Python 3.11+, FFmpeg/FFprobe, OpenSSH. 비밀번호로 SSH에 연결하려면 `sshpass`도 필요합니다. 로컬 컴퓨터에 NVIDIA GPU는 없어도 됩니다.
- **클라우드 환경**: 현재 배포 자료는 AutoDL의 RTX PRO 6000 Blackwell 96GB를 대상으로 합니다. 최소 120 GiB 메모리와 320 GB의 영구 디스크 여유 공간이 필요하며, 모델 8개의 총용량은 약 156.45 GB입니다.
- **제작 입력 자료**: 토크 영상의 전체 SRT, 콘텐츠 스타일 참고 자료, 원본 영상과의 연결을 위한 참고 자료, 이번 생성 작업의 예산.

저장소 접근 권한을 받은 뒤, 로컬 컴퓨터에서 복제하고 설치합니다.

```bash
git clone https://github.com/erduo1998-cell/h3loom.git h3loom
cd h3loom
uv sync --frozen
source .venv/bin/activate
```

uv가 없다면 `python3 -m venv .venv`로 환경을 만들고 활성화한 뒤 `python -m pip install -e .`를 실행할 수 있습니다. Codex에서 복제한 디렉터리를 열고 Agent가 `AGENTS.md`를 읽도록 하세요. 프로젝트에 Skill 세 개가 포함되어 있으므로 전역 설치본을 덮어쓸 필요는 없습니다.

먼저 테스트용 자막으로 시작 명령을 확인합니다. 이 단계에서는 유료 생성을 허용하지 않습니다.

```bash
broll-video init --name "安装检查" --srt examples/demo.srt --ratio 16:9 --execution estimate_only
broll-video next <task-id>
```

`<task-id>`에는 앞선 명령이 반환한 작업 번호를 넣습니다. 본격적인 제작 전에는 [운영 안내서](docs/getting-started.md)에 따라 클라우드 배포, 시각적 결과 확인, 이번 작업의 예산 승인을 완료하세요. 새 GPU에 배포할 때는 실제 장비 검증이 필요합니다. 모든 클라우드, GPU, 이미지 생성 백엔드에서 곧바로 실행된다고 보장하지 않습니다.

## 💬 유료 상담과 시드 회원

**제작자: 刘冉 / 耳总. 상담은 유료 서비스입니다.**

**시드 회원 그룹에 가입하면 영구 상담 자격을 얻을 수 있습니다.** 클라우드 배포, 영상 생성 작업 흐름, 개인 스타일 다듬기, 시드 회원 가입 방법을 알고 싶다면 QR 코드를 스캔해 개인 WeChat을 추가하고, 메모에 **「MiniMax H3 种子会员」**을 적어 주세요. 가입 비용과 상담 범위를 안내받을 수 있습니다.

<p align="center">
  <img src="docs/images/wechat-qrcode.jpg" alt="刘冉 / 耳总의 개인 WeChat QR 코드: 유료 상담 및 시드 회원 문의" width="260" />
</p>

<p align="center"><strong>유료 상담 · 시드 회원에게 영구 상담 자격 제공</strong><br/>개인 상담 창구이며, MiniMax나 AutoDL의 공식 고객 지원이 아닙니다.</p>

<p align="center"><a href="https://erduo.art">개인 웹사이트</a> · <a href="https://github.com/erduo1998-cell">GitHub @erduo1998-cell</a></p>

## 📚 더 알아보기

[설치 및 운영 안내서](docs/getting-started.md) · [제작 흐름](docs/three-stage-workflow.md) · [이전 범위](docs/migration-scope.md) · [완료한 검증](docs/migration-validation.md) · [외부 자료 출처 및 라이선스 상태](THIRD_PARTY_NOTICES.md)

실제 영상의 화면, 글자, 소리는 사람이 확인해야 합니다. 소개 이미지와 개인 WeChat QR 코드의 출처 및 게재 목적은 [README 자료 기록](docs/readme-assets.md)을 참고하세요.
