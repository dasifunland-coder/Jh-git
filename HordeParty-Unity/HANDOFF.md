# HordeParty 유니티 리메이크: 3단계 이어받기 (PC의 Claude Code용)

작성: 2026-11-28 · 보낸 쪽: 클라우드 Claude Code 세션 · 받는 쪽: 장현님 PC의 Claude Code (데스크톱 앱)

먼저 `D:\gamedev-tools\HordeParty_유니티_인수인계.md`를 읽으세요. 이 문서는 그 문서의 7번 진행 순서 중 **3단계(몹 1만 마리 기술 검증)** 진행 상황만 다룹니다.

## 0. 한 줄 요약

3단계 코드(Burst 그리드 + 인스턴싱 + VAT + 벤치마크 HUD/CSV)는 작성되어 GitHub에 올라가 있지만, **Unity에서 한 번도 컴파일하거나 실행해 보지 않았습니다.** 이번 세션이 할 일은 1단계(프로젝트 생성) → 코드 넣기 → 컴파일 오류 수정 → 실행 → 측정 → 2단계(에셋)와 실제 모델 검증입니다.

## 1. 지금까지 된 것과 안 된 것

| 항목 | 상태 |
|---|---|
| using-unity 스킬 확인 | 클라우드 세션에서는 안 보였음 (스킬이 PC에만 있음). **이 세션에서 다시 확인할 것** |
| 1단계 프로젝트 생성 | 안 됨 (클라우드에 Unity 없음) |
| 2단계 에셋 임포트 | 안 됨 (원본 에셋이 PC에 있음) |
| 3단계 코드 | 작성 완료. Roslyn C# 9 문법 검사만 통과. Unity API 기준 컴파일은 미검증 |
| 3단계 측정 | 안 됨 |
| Godot 원본 대조 | 안 됨. 원본 `mob_system.gd`는 아직 아무도 함수 단위로 읽지 않음 |

## 2. 코드 위치

- 저장소: GitHub `dasifunland-coder/Jh-git`, 브랜치 **`ccr-1543d22e-5cr2qt`**, 폴더 `HordeParty-Unity/`
- `HordeParty-Unity/README.md`: 사람용 설치·실행 안내, 파일별 역할 표, 통과 기준 제안
- `HordeParty-Unity/Assets/HordeParty/`: 새 유니티 프로젝트의 `Assets/` 아래에 그대로 복사할 폴더

```
Assets/HordeParty/
  Runtime/HordeParty.Runtime.asmdef      (참조: Unity.Burst, Unity.Mathematics)
  Runtime/Mobs/MobData.cs                MobSim(CPU), MobGpu(GPU, 32바이트), HitEvent, MobState
  Runtime/Mobs/MobJobs.cs                BuildGridJob → SteerJob → DamageJob → CompactJob (전부 Burst)
  Runtime/Mobs/MobSystem.cs              배열 보관, 잡 예약, 종류별 Graphics.RenderMeshPrimitives
  Runtime/Mobs/VatClipSet.cs             VAT 텍스처 + 클립 표 (ScriptableObject)
  Runtime/Mobs/ProceduralMobFactory.cs   에셋 없이 쓰는 임시 메시 + 걷기/공격/사망 VAT
  Runtime/Bench/BenchHeroes.cs           임시 영웅 5명, 주기적 범위 피해
  Runtime/Bench/MobBenchmark.cs          몹 4종 구성, 생성, 자동 밀도, HUD(IMGUI), CSV 벤치마크
  Shaders/MobVAT.shader                  URP HLSL: ForwardLit / ShadowCaster / DepthOnly / DepthNormals
  Editor/HordeParty.Editor.asmdef
  Editor/BenchmarkSceneBuilder.cs        메뉴: 씬 생성, Windows 빌드
  Editor/VatBakerWindow.cs               메뉴: 스킨드 메시 + 클립 → VAT 굽기
```

## 3. 할 일 (순서대로)

1. **스킬 확인.** using-unity 스킬이 보이는지 장현님께 보고
2. **프로젝트 생성.** Unity 6.3 LTS `F:\6000.3.29f1\Editor\Unity.exe`, URP(Universal 3D 템플릿), 원본 폴더 밖. 위치는 장현님께 확인 (예: `D:\Projects\HordeParty_Unity`). using-unity의 `new-unity-project`를 쓸 수 있으면 그것으로
3. **브랜치 받기.** `git clone -b ccr-1543d22e-5cr2qt https://github.com/dasifunland-coder/Jh-git` 후 `HordeParty-Unity/Assets/HordeParty`를 새 프로젝트 `Assets/`에 복사
4. **패키지 확인.** `Packages/manifest.json`이나 `packages-lock.json`에 `com.unity.burst`, `com.unity.mathematics`가 있는지 확인. 없으면 추가
5. **컴파일.** Unity를 열거나 배치 모드로 실행해서 `Editor.log`의 오류를 읽고 고친다 (아래 4번의 의심 지점부터)
6. **씬 생성과 실행.** 메뉴 `HordeParty/Create Mob Benchmark Scene` (배치 모드라면 `-executeMethod HordeParty.EditorTools.BenchmarkSceneBuilder.CreateScene`) → Play로 몹이 보이고 움직이는지 장현님께 확인 요청
7. **빌드와 측정.** `HordeParty.EditorTools.BenchmarkSceneBuilder.BuildWindows` → `Builds/MobBenchmark/HordePartyBench.exe -hpbench`, `-hpbench -noshadows` 각각 실행 → `%USERPROFILE%\AppData\LocalLow\<회사>\<제품>\mob_benchmark_*.csv`를 읽고 표로 보고
8. **2단계와 실제 모델 검증.** glTFast(`com.unity.cloud.gltfast`) 설치 → KayKit 해골 `*_ual.glb` 임포트(애니메이션은 Generic 또는 Legacy) → `HordeParty/VAT Baker`로 클립 순서 0 걷기, 1 공격, 2 사망으로 굽기 → `MobBenchmark.overrideVat`에 지정 → 다시 측정
9. 결과를 보고 통과 여부와 다음 수(5번)를 장현님과 정한 뒤 4단계로

## 4. 컴파일·실행 때 먼저 의심할 곳

검증 없이 작성했으므로 아래가 깨질 가능성이 가장 높습니다.

| 곳 | 의심 내용 | 대안 |
|---|---|---|
| `MobVAT.shader` 인스턴스 ID | `Graphics.RenderMeshPrimitives`에서 `SV_InstanceID`를 그대로 씀. 몹이 한 자리에 겹치거나 안 보이면 이것부터 | `#include "UnityIndirect.cginc"` 방식이나 `RenderMeshIndirect`로 변경 |
| `MobVAT.shader` 인클루드 | URP 17.3에서 `ApplyShadowBias`, `PackFloat2To888`, `GetWorldSpaceNormalizeViewDir` 이름·위치가 바뀌었을 수 있음 | URP 패키지의 `ShaderLibrary`에서 실제 이름 확인 |
| `MobVAT.shader` `_BaseMap` 선언 | Lighting.hlsl 쪽과 중복 선언 오류가 나면 | 이름을 `_MobBaseMap`으로 바꾸고 C# 쪽도 맞춤 |
| 그림자 키워드 | Unity 6.3 URP의 소프트 섀도 키워드가 다를 수 있음 | URP Lit.shader의 `multi_compile` 줄을 그대로 복사 |
| `MaterialPropertyBlock.SetInteger` + 셰이더 `int _InstanceOffset` | 값이 안 들어가면 모든 종류가 0번부터 읽음 | `SetFloat` + 셰이더 `float`로 바꾸고 `(uint)` 캐스팅 |
| `FrameTimingManager` | GPU ms가 계속 0이면 | `PlayerSettings.enableFrameTimingStats` 확인. 에디터에서는 원래 n/a일 수 있음 |
| Input System | 코드에서 `UnityEngine.Input`을 쓰지 않음 (IMGUI 이벤트만). 입력 관련 예외가 나면 다른 곳 문제 | |
| VAT Baker | `AnimationClip.SampleAnimation` + `BakeMesh` 결과 좌표계. 모델이 눕거나 커지면 `toRoot` 행렬 쪽 | |

## 5. 측정 결과에 따른 다음 수

- **GPU 병목** (GPU ms 높음): 컴퓨트 셰이더로 화면 밖 컬링 + `RenderMeshIndirect`, 거리별 LOD 메시(VAT 2벌), 먼 몹 그림자 끄기
- **CPU 병목** (Sim ms 높음): `MobSystem.Update`의 `compact.Complete()`를 `LateUpdate`로 옮겨 메인 스레드와 겹치기, `BuildGridJob` 병렬화
- **둘 다 여유:** 이 구조 그대로 4단계(영웅 5직업 전투). 시체(700)·코인(1,800)·파편(4,000)도 같은 인스턴싱 방식으로

통과 기준(제안, 장현님 확정 필요): 1만 마리·1080p·몹 그림자 켬에서 평균 60 FPS 이상, 1% low 50 이상, Sim 2ms 이하. 실제 해골 VAT로도 유지.

## 6. 설계 결정 (바꿀 때는 장현님께 확인)

- 몹은 ECS(Entities)가 아니라 **NativeArray + Burst 잡 + 직접 그리기**. 원본 mob_system.gd 구조(Packed 배열 + MultiMesh)와 1:1로 대응되고 패키지 부담이 적어서
- 잡은 매 프레임 `Update`에서 즉시 완료 (측정 정확도 우선)
- 이웃 밀어내기는 주변 3×3 셀, 검사 수 상한 24
- 죽은 몹은 순서를 유지하며 압축하고, GPU 버퍼는 종류별로 묶어서 종류마다 그리기 1회
- 원본의 FPS 기반 자동 밀도 조절은 `MobBenchmark.autoAdjust`로 재현 (기본 꺼짐)
- 수치(속도, 체력 등)는 지금 `MobBenchmark.Awake`에 하드코딩. 인수인계 문서 8번대로 이후 ScriptableObject로 분리할 것

## 7. 지켜야 할 것 (인수인계 문서 9번 재확인)

- 원본 `C:\Users\Janghyun\Documents\HordeParty`는 읽기만
- `marketing/`, `shots/`, `.godot/`는 옮기지 않음
- 힉스필드 크레딧을 쓰는 작업, 유료 API 키가 필요한 작업은 실행 전에 장현님께 확인
- 원본 스크립트는 이식 전에 직접 읽을 것 (인수인계 문서의 역할 설명은 머리말 주석 기준)
