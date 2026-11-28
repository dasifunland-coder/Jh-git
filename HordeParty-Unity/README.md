# HordeParty 유니티 리메이크: 3단계 몹 1만 마리 기술 검증

인수인계 문서 7번의 **3단계(인스턴싱 + Burst 그리드 + VAT)** 코드입니다.
Unity 6.3 LTS (6000.3.29f1) + URP 기준으로 작성했습니다.

> **주의:** 이 코드는 클라우드 세션에서 작성했습니다. 거기서는 장현님 PC의 Unity와 원본 폴더에 접근할 수 없었습니다.
> 그래서 C# 문법 검사(Roslyn)만 통과했고, **Unity 컴파일과 실행 검증은 아직 하지 않았습니다.**
> 처음 열 때 오류가 나면 Console 메시지를 그대로 붙여 주세요.

## 1. 프로젝트 만들기 (1단계)

1. Unity Hub → New project → 에디터 **6000.3.29f1** → 템플릿 **Universal 3D**
2. 위치는 원본 폴더 밖으로 지정합니다. 예: `D:\Projects\HordeParty_Unity`
3. Window → Package Manager에서 **Burst**와 **Mathematics**가 설치되어 있는지 확인합니다.
   URP가 의존하므로 보통 이미 들어 있습니다. 없으면 `+` → *Install package by name* → `com.unity.burst`, `com.unity.mathematics`
4. 이 저장소의 `HordeParty-Unity/Assets/HordeParty` 폴더를 새 프로젝트의 `Assets/` 아래에 복사합니다.

## 2. 실행

| 하는 일 | 방법 |
|---|---|
| 씬 만들기 | 메뉴 **HordeParty → Create Mob Benchmark Scene** → `Assets/HordeParty/Scenes/MobBenchmark.unity` 생성 |
| 에디터에서 보기 | Play. 왼쪽 위 HUD에서 몹 수 버튼(1k~20k), 그림자, 영웅 공격, 자동 밀도를 켜고 끔 (F1로 숨김) |
| 정확한 측정 | 메뉴 **HordeParty → Build Mob Benchmark (Windows)** → `Builds/MobBenchmark/HordePartyBench.exe` |
| 자동 측정 | `HordePartyBench.exe -hpbench` (그림자 끄고 측정: `-hpbench -noshadows`). 1k·5k·10k·12k·15k·20k를 단계별로 측정하고 CSV를 저장한 뒤 종료 |
| 결과 파일 | `%USERPROFILE%\AppData\LocalLow\<회사명>\<제품명>\mob_benchmark_*.csv` (HUD 맨 아래에도 경로 표시) |

에디터 수치는 에디터 자체 부하가 섞이고 GPU ms가 `n/a`로 나올 수 있으므로, 판단은 빌드 수치로 합니다.

### 통과 기준 (제안, 장현님이 정하시면 됩니다)

- **1만 마리, 1080p, 몹 그림자 켬:** 평균 60 FPS 이상, 1% low 50 이상
- **Sim(시뮬레이션) 2ms 이하** (CPU 쪽 여유. 이후 영웅·이펙트·UI가 들어갈 자리)
- 1.2만(원본 상한)에서도 위 기준 근처
- 실제 해골 모델(VAT, 버텍스 수천 개)로 바꿔도 위 기준 유지 ← 이게 진짜 관문

## 3. 구조 (Godot → Unity)

| 파일 | 하는 일 | 원본 대응 |
|---|---|---|
| `Runtime/Mobs/MobSystem.cs` | NativeArray 보관, 잡 예약, 종류별 `Graphics.RenderMeshPrimitives` 1회 | mob_system.gd (Packed 배열 + MultiMesh) |
| `Runtime/Mobs/MobJobs.cs` | Burst 잡 4개: 격자 구축(카운팅 정렬) → 영웅 추적·밀어내기 → 범위 피해 → 사망 몹 압축 + GPU 데이터 작성 | 밀도 그리드 밀어내기 O(N) |
| `Runtime/Mobs/MobData.cs` | 시뮬레이션 구조체, GPU 구조체(32바이트) | 인스턴스 커스텀 데이터 |
| `Shaders/MobVAT.shader` | URP HLSL. StructuredBuffer 인스턴스 + VAT 보간 + 그림자/깊이/노멀 패스 + 림 라이트 + 피격 플래시 + 안개 | MultiMesh 셰이더 + darkmode 림 라이트 |
| `Runtime/Mobs/VatClipSet.cs` | VAT 텍스처와 클립 표 (ScriptableObject) | 없음 (원본 README의 다음 단계) |
| `Runtime/Mobs/ProceduralMobFactory.cs` | 에셋 없이 검증하기 위한 임시 몹 메시와 걷기·공격·사망 VAT | |
| `Runtime/Bench/BenchHeroes.cs` | 임시 영웅 5명(전사·궁수·마법사·도적·성기사). 주기적으로 범위 피해를 넣어 사망·재생성이 계속 일어나게 함 | hero.gd (4단계에서 새로 만듦) |
| `Runtime/Bench/MobBenchmark.cs` | 몹 4종 구성, 생성, FPS 자동 밀도 조절, HUD, CSV 벤치마크 | 원본의 FPS 기반 자동 조절 |
| `Editor/BenchmarkSceneBuilder.cs` | 씬 생성, Windows 빌드 메뉴 | |
| `Editor/VatBakerWindow.cs` | 스킨드 메시 + 클립 → VAT 굽기 | blender-skills의 VAT 굽기 대안 |

몹 4종(슬라임·질주꾼·돌격병·군주)은 지금은 같은 임시 메시에 색, 크기, 속도, 체력만 다르게 줬습니다.
각 종류는 `KindConfig`에 메시, 머티리얼, VAT를 따로 넣을 수 있게 되어 있습니다.

## 4. 실제 모델로 검증하기 (2단계와 연결)

1. Package Manager → *Install package by name* → `com.unity.cloud.gltfast`
2. KayKit 해골의 `*_ual.glb`를 임포트합니다. 애니메이션은 **Generic** 또는 **Legacy**로 임포트해야 합니다 (Humanoid는 굽기가 안 될 수 있음)
3. **HordeParty → VAT Baker**: 모델 지정 → "모델에 포함된 클립 불러오기" → 순서를 **0 걷기, 1 공격, 2 사망**으로 맞춤 → Bake
4. 씬의 `MobBenchmark` 오브젝트 → **Override Vat**에 만들어진 `*_VAT.asset`을 지정하고 다시 측정합니다

버텍스 수 부하만 먼저 보려면 `MobBenchmark`의 Radial Segments와 Rings를 올리면 됩니다 (예: 48 × 40 ≈ 2,000 버텍스).

## 5. 측정 결과에 따른 다음 수

- **GPU가 병목일 때** (GPU ms가 높음): 컴퓨트 셰이더로 화면 밖 몹 컬링 + `RenderMeshIndirect`, 거리별 LOD 메시(VAT 2벌), 먼 몹 그림자 끄기
- **CPU가 병목일 때** (Sim ms가 높음): 잡 완료를 `LateUpdate`로 미뤄 메인 스레드와 겹치기 (`MobSystem.Update` 주석 참고), 격자 구축 병렬화
- 둘 다 여유가 있으면 이 구조 그대로 4단계(영웅 전투)로 갑니다. 시체(최대 700), 코인(1,800), 파편(4,000)도 같은 인스턴싱 방식으로 처리합니다

## 6. 아직 안 한 것

- 2단계 에셋 임포트 (원본 에셋이 장현님 PC에 있음)
- 원본과 나란히 실행해 보는 비교
- 횃불 같은 추가 광원 (셰이더는 지금 메인 라이트만 받음. 9단계 연출 때 Forward+ 추가 광원을 넣을 예정)
