# HEXA Studio — 통합 제작 환경 설계 v0.4

작성일: 2026-11-26  
상태: 브라우저 기반 Studio v0.1 초기 구현. 실제 Chrome/ComfyUI 검증 전.

## 1. 목표 및 결정 사항

개인용 AI 애니메이션/MV 제작 환경을 웹 기반으로 구축한다. 기존 PREVIS, DANCE, EXPRESSION의 검증된 기능을 보존하고 단계적으로 통합한다. DANCE는 안무 전용이 아니라 CHARACTER로 확장한다.

- DB, Redis, 메시지 브로커 없이 프로젝트별 파일 시스템을 영속 저장소로 사용한다.
- 프로젝트마다 독립 Git 저장소를 사용할 수 있도록 한다. 프로그램 소스와 제작 데이터는 분리한다.
- 브라우저는 UI, HEXA Core는 실행 및 오케스트레이션 주체다.
- Windows RTX 5080 16GB에서 로컬 ComfyUI를 활용한다. GPU 생성은 기본 순차 실행한다.
- 초기에는 기존 HTML을 iframe으로 통합하고 postMessage 계약을 정의한다. 검증 후 점진적으로 모듈화한다.
- 최종 목표는 캐릭터 제작 → 캐스팅 → 연출 → 이미지 → 영상 → 편집의 연결이다.

## 2. 모듈

| 모듈 | 책임 |
|---|---|
| PROJECT | 생성, 열기, 저장, 프로젝트 복제, Git 상태 |
| CHARACTER | 원화, 체형, 포즈, 손동작, 표정, 의상, 동작 라이브러리 |
| PREVIS | 캐스팅, 공간, 소품, 카메라, 연기, 타임라인, 콘티 PNG/JSON |
| IMAGE | 프롬프트 조합, ComfyUI 후보 생성, 검수, 키이미지 확정 |
| MOTION | H3 등 영상 워크플로, 클립 후보, 재생성, 검수 |
| EDITOR | 음원/가사/파트 싱크, 컷 편집, FFmpeg 출력 |

CHARACTER의 캐릭터 에셋은 PREVIS에서 참조한다. 확정 컷은 당시 캐릭터 버전과 입력 스냅샷을 보존하여 이후 체형 수정으로 기존 컷이 변하지 않게 한다.

## 3. 아키텍처

```text
Browser (React / TypeScript / Vite / Three.js)
  PROJECT | CHARACTER | PREVIS | IMAGE | MOTION | EDITOR
                     REST / WebSocket
HEXA Core (Python / FastAPI, 단일 로컬 프로세스)
  Project Manager | Asset Manager | Workflow Engine
  Job Scheduler | Process Manager | Event Manager
  Git Adapter | ComfyUI Adapter | FFmpeg Adapter
       |              |              | 
  Project Files      Git         ComfyUI / FFmpeg
```

Core는 파일 저장, 실행 요청, 작업 큐, 결과 수집, 진행 이벤트, 재시작 복구를 담당한다. 브라우저 종료와 작업 수명은 독립적이다. 단, PREVIS의 WebGL PNG 추출은 브라우저에서 수행하고 입력 PNG/JSON 저장을 완료한 뒤 서버 작업을 등록한다. 서버 자체의 PREVIS 렌더링은 별도 후속 과제다.

운영 시 FastAPI가 빌드된 프런트엔드를 서빙한다. start.bat으로 Core 시작, ComfyUI 연결 확인, 작업 복구, 브라우저 열기를 수행한다. 기본 localhost 바인딩. LAN/외부 접근은 인증 및 VPN 등 별도 보안 설계 후 허용한다.

## 4. 파일 기반 프로젝트

```text
HEXA/
  studio/                 # 프로그램 저장소
  workflows/              # 공통 워크플로 템플릿
  library/                # 공유 캐릭터/포즈/표정/소품
  projects/
    aesther-school/
      .git/
      project.json
      characters/
        karin/
          character.json
          body.json
          reference/
      audio/
        master.mp3
        lyrics.json
      scenes/
        S001/
          scene.json
          previs.json
          storyboard/
          prompts/
          images/
            candidates/
            approved/
          videos/
            candidates/
            approved/
      workflows/          # 사용한 워크플로 스냅샷
      timeline.json
      jobs/
      exports/
      backups/
```

project.json에는 schemaVersion, projectId, 이름, 해상도, FPS, 장면 ID 목록 등을 둔다. 장면 및 에셋은 안정적인 ID와 프로젝트 상대경로로 참조한다. 공유 라이브러리에서 가져온 에셋은 프로젝트에 복사하거나 버전 고정하여 프로젝트 이동 시 재현성을 유지한다. 확정 결과는 생성 입력, 워크플로 버전, 모델 식별자, 시드, 결과 경로를 기록한다.

파일 저장은 임시 파일 후 동일 파일 시스템 내 원자적 교체를 사용한다. JSON은 안정적인 포맷과 키 순서를 유지한다. 파일 잠금 및 revision 검사로 다중 탭의 덮어쓰기를 방지한다. 여러 파일 변경은 단일 원자적 트랜잭션이 아니므로 실패 복구 절차를 둔다. 스키마 변경은 마이그레이션과 백업을 제공한다. 경로 검증으로 프로젝트 외부 파일 접근을 차단한다.

## 5. Git 정책

- JSON, 프롬프트, 타임라인, 워크플로는 일반 Git.
- 원화 및 확정 이미지/영상/음원은 필요 시 Git LFS. 원격 용량/전송량 및 저작권 고려.
- 생성 후보, 캐시, 임시 파일, 실행 중 작업 로그는 기본 gitignore. 필요한 후보는 별도 백업 가능.
- 자동 저장은 파일 저장만 수행한다. 의미 있는 제작 단위에서 사용자가 커밋/푸시한다.
- Git UI는 status, diff, commit, history, push를 단계적으로 지원한다. 파괴적 복원은 명시적 확인 필요.
- 후보는 덮어쓰지 않는다. 확정 파일과 메타데이터는 함께 관리한다.

## 6. 실행 모델

예: 이미지 후보 4장 생성
1. 브라우저에서 PREVIS PNG/JSON을 내보내고 Core에 저장.
2. Core가 캐릭터 원화, 프롬프트, 워크플로 입력을 스냅샷으로 고정.
3. 작업별 JSON을 jobs/에 기록하고 GPU 큐 등록.
4. ComfyUI에 순차 요청, 진행 상황을 WebSocket으로 전달.
5. 결과를 고유 파일명으로 저장하고 후보 메타데이터 등록.
6. 사용자 검수 및 확정 후 MOTION 입력으로 전달.

작업 상태: queued → running → succeeded / failed / cancelled. 외부 prompt ID, 입력 스냅샷, 시도 횟수, 오류, 결과 경로를 저장한다. 재시작 시 ComfyUI 상태/이력을 확인하고 중복 제출을 피한다. 확인 불가능한 작업은 자동 성공 처리하지 않는다. 취소 및 재시도는 어댑터 지원 범위에 맞춘다.

워크플로 정의 예시 (향후 확장용, 실행 가능한 현재 API 아님):

```json
{
  "name": "키이미지 후보 생성",
  "steps": [
    {"action": "previs.export"},
    {"action": "prompt.compose"},
    {"action": "comfyui.generate", "count": 4},
    {"action": "asset.register"},
    {"action": "review.wait"}
  ]
}
```

초기에는 Python 함수 기반 실행기로 충분하다. 범용 JSON 엔진은 필요할 때 확장한다. 사용자 검수는 서버 작업을 장시간 점유하지 않는 별도 상태로 관리한다.

## 7. ComfyUI 연동

예상 API: /system_stats, /object_info, /upload/image, /prompt, /ws, /history/{id}, /view. 실제 설치 버전에서 검증한다. API 형식 워크플로 템플릿에 프롬프트, 참조 이미지, 시드, 해상도 등을 주입한다. 모델/노드/입력 호환성은 제출 전 검사한다. H3 전용 로직을 Core에 고정하지 않고 모델별 어댑터를 둔다. RTX 5080에서 VRAM, 생성 시간, 실패 복구를 실제 측정한다.

## 8. 구현 로드맵

1. 통합 웹 셸, Core, 프로젝트 생성/열기/저장, 기존 HTML 실행. DB 없음.
2. CHARACTER 에셋 스키마, DANCE/EXPRESSION 통합, 원화 및 체형 저장.
3. PREVIS 캐스팅, 장면 관리, PNG/JSON 자동 저장, 기존 체형 필드 호환 검증.
4. IMAGE: ComfyUI 연결, 후보 2장 MVP, 검수 및 확정.
5. MOTION: H3 클립 생성, 큐, 재생성, 복구.
6. EDITOR: 음원 싱크, 컷 편집, FFmpeg 최종 출력.

Phase 1 완료 기준: start.bat으로 실행, 프로젝트 폴더 생성 및 재열기, 기존 도구 실행, JSON 왕복 저장, 재시작 후 데이터 유지, Git으로 프로젝트 변경 확인. 기존 HTML의 동작 회귀가 없어야 한다.

## 9. 표준 컷 및 시간 기준

- 기본 제작 컷 4초, 24fps 기준 96프레임. 최종 출력 기본값 2560×1440.
- 현재 사용자 로컬 MiniMax H3 환경의 최대 생성 길이 5초를 기준으로 한다. 실제 지원 프레임 수 및 FPS는 워크플로에서 검증한다.
- 최대 5초 생성 후 4초 채택 시 총 1초의 편집 여유를 확보할 수 있다. 앞뒤 트림은 가변이며 여유분 생성은 선택 사항이다.
- 4초는 기본값이지 강제 길이가 아니다. 음악과 연출에 따라 컷 길이를 조정한다. 모델 제한을 넘는 장면은 여러 생성 컷으로 분할한다.
- PREVIS 장면과 생성 컷, 최종 편집 클립을 별도 ID로 관리한다. 한 장면에 여러 컷이 포함될 수 있다.
- 컷 메타데이터에 목표 길이, 생성 길이, 생성 FPS, 타임라인 시작 프레임, source in/out을 기록한다. 편집 시간은 정수 프레임 기준으로 관리하고 모델별 생성 FPS와 최종 FPS를 구분한다.
- 모델별 최대 길이는 어댑터 capability로 관리하며 전역 5초 제한을 하드코딩하지 않는다.
- 약 250초 MV는 4초 기준 약 63컷이며 실제 컷 수는 음원 및 연출에 따라 달라진다.

## 10. 미결 사항

- 신규 hexa-studio 저장소 분리 시점과 기존 HTML 동기화 방식.
- CHARACTER/PREVIS 공통 스키마 및 좌표계, 체형 필드 호환성.
- 실제 ComfyUI/H3 워크플로 및 GPU 성능.
- Git LFS 원격 저장소 정책, 후보 파일 백업 정책.
- 편집 타임라인 포맷과 외부 편집기 연동 범위.

## 11. 공통 에셋 관리

에셋 유형: characters, locations, props, actions, cameras, lighting, styles, workflows. 각 에셋은 독립 ID, asset.json, 참조 파일, 향후 썸네일/태그/버전을 가진다. 장소는 공간 구조와 배경 원화, 소품은 형상과 재질, 액션은 포즈 및 키프레임, 카메라/조명은 촬영 프리셋을 포함한다. 공용 라이브러리는 후속 구현하며 프로젝트에 가져온 에셋은 스냅샷으로 보존한다.

제작 순서: 캐릭터 → 장소 → 씬/소품 배치 → 액션/표정/시선 → 카메라/조명 → 키이미지 → 영상 → 편집.

## 12. 브라우저 우선 MVP

hexa-studio.html을 기존 저장소에 추가한다. React/FastAPI 전환 전의 독립 HTML 프로토타입이다. Chrome/Edge의 File System Access API(showDirectoryPicker, createWritable)를 통해 HTTPS 또는 localhost에서 사용자 승인 폴더에 접근한다. 매 세션 폴더를 다시 선택한다. 브라우저 권한 및 파일 잠금 한계가 있으므로 서버 기반 동시 쓰기 제어는 후속 과제다.

현재 구현 범위:
- 프로젝트 폴더 선택, project.json 생성/열기/저장, 외부 변경 감지.
- 24fps, 96프레임 기본 컷, 1~120프레임 조절. 초기에는 컷별 scenes/<cutId>/ 폴더를 사용하며 장면/컷 분리 모델은 후속 과제.
- 프로젝트 assets/<type>/<id>/asset.json 및 원본 파일 저장, 디렉터리 스캔, 컷별 에셋 선택. 현재 유형마다 단일 에셋 선택이며 복수 캐스팅 및 배치 연동은 후속 과제.
- 기존 DANCE, EXPRESSION, PREVIS iframe 연결. 탭 전환 시 기존 편집기에서 먼저 저장해야 한다. 자동 데이터 전달/postMessage는 아직 미구현.
- 컷별 PREVIS/IMAGE/MOTION/EDITOR 결과 파일 수동 등록. 생성 또는 편집 엔진을 실행하지 않는다.
- Git/FFmpeg/ComfyUI 실행, 백그라운드 작업 큐는 향후 HEXA Core에서 구현. 브라우저 자체는 임의 로컬 프로세스를 실행할 수 없다.

다음 단계: Chrome 실사용 테스트, 에셋 복수 선택 및 썸네일/태그, 기존 편집기 데이터 브리지, 이후 Core API 및 작업 큐. 기존 HTML 자체는 이번 작업에서 변경하지 않는다.


## 13. Pipeline-first v0.2 (현재 구현)

이 절은 앞 절의 초기 프로토타입 구조보다 우선한다. 핵심 에셋은 캐릭터(원화 + DANCE 체형 JSON)와 장소(원화 + PREVIS 무대 JSON) 두 종류로 단순화한다. 건축 모델링은 범위에서 제외한다. 소품, 액션, 카메라, 조명은 PREVIS 설정 및 프리셋, 스타일은 프롬프트, 워크플로는 실행 설정으로 취급한다.

```text
project.json                 # schemaVersion 2, cuts: ID 배열
characters/<id>/asset.json  # 원화, JSON, MD 등 원본 파일 목록
locations/<id>/asset.json
cuts/<cid>/cut.json          # frames, characters, location, keyframes
cuts/<cid>/previs.json
cuts/<cid>/direction.md
cuts/<cid>/motion_prompt.md
cuts/<cid>/keyframes/<kid>/keyframe.json # frame: 0-based
cuts/<cid>/keyframes/<kid>/previs.png
cuts/<cid>/keyframes/<kid>/prompt.md
output/<cid>/keyframes/<kid>/candidate_*.png
output/<cid>/keyframes/<kid>/result.json
output/<cid>/videos/candidate_*.mp4
output/<cid>/videos/result.json
output/<cid>/plan.json
```

경로는 프로젝트 루트 기준 상대경로. result.json의 approved는 같은 폴더 내 후보 파일명, state=running 및 error는 선택적인 실행 상태 필드. 파일 존재를 확인하여 진척을 계산한다. 입력 변경에 따른 확정 결과의 stale 판정은 향후 구현한다. v1 프로젝트는 자동 덮어쓰기/마이그레이션하지 않는다. 신규 폴더로 테스트한다.

Studio v0.2: PRODUCTION 실제 파일 기반 현황판, 필터, 컷 상세, 이미지 확대, 영상 재생, 승인; DIRECTOR 컷 길이/캐스팅/장소/프롬프트/키프레임; ASSETS 캐릭터/장소 등록. 기존 편집기와는 수동 내보내기/가져오기. 편집기 탭은 확정 영상 조회까지만 제공한다.

Python 3.10+ 표준 라이브러리 CLI:

```bash
python hexa.py validate --project PATH
python hexa.py status --project PATH
python hexa.py plan --project PATH
```

선택적으로 --cut ID. plan은 검증을 통과한 컷의 프롬프트 조합과 입력 SHA256을 output/<cid>/plan.json에 저장하며 생성 요청을 보내지 않는다. 실제 ComfyUI 노드 매핑/업로드/작업 큐/결과 수집 및 오류 복구는 다음 단계다. 여러 키프레임 중 실제 영상 모델이 지원하는 입력만 전달하고 나머지는 검수 레퍼런스로 사용한다. 컷의 기본값은 96프레임(4초), 생성 모델 capability는 별도 검증한다. 브라우저와 Python이 같은 파일을 동시에 수정하지 않도록 현재는 사용자 작업 순서를 분리한다. 실제 브라우저 및 GPU 통합 테스트 미수행.
