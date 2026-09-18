"""
학생용 브라우저 감시 프로그램 (보조 도구)

이 프로그램은 교사가 원격으로 학생 화면을 직접 감시하는 상황을 보조하는
도구입니다. 완벽한 차단 시스템이 아니라, 검색/검색결과 화면이나 Gemini(제미나이)
같은 대상이 "화면에 떠 있는 상태로 방치되는 것"을 자동으로 정리해 주는 역할을
합니다. 아래 항목들은 의도적인 설계 결정이며, 버그가 아닙니다.

1. 판단 기준이 창 제목(title) 문자열뿐입니다. 학생이 JS로 document.title을
   바꿔 우회할 여지는 있지만, 1.5초 간격으로 반복 검사하므로 실질적으로
   우회를 시도하는 시점에 이미 종료되며, 교사의 실시간 감시를 보조하는
   용도이므로 이 정도 한계는 감수합니다.
2. 화이트리스트에 "Google"을 넓게 포함시켜 다른 구글 서비스는 대부분
   허용됩니다. 실제로 반드시 막아야 하는 대상은 Gemini(제미나이)이므로,
   블랙리스트에서는 Gemini 계열을 최우선으로 확실하게 잡는 데 집중합니다.
3. "로그인"/"Sign in" 류 키워드를 화이트리스트에 유지합니다. Google 로그인이
   끝나면 원래 사이트(Classroom 등)로 리다이렉트되는데, 그 과정에서 창이
   꺼지지 않도록 하기 위함입니다.
4. 백그라운드(비활성) 탭은 감시하지 않습니다. 목적이 "검색/검색결과 화면이
   보이는 것"을 막는 것이므로 화면에 보이지 않는 탭까지 감시할 필요가
   없습니다. GetWindowText는 어차피 활성 탭의 제목만 돌려주므로 별도 처리도
   필요 없습니다.
5. 브라우저 자체 시스템 다이얼로그(로그인 후 "시작하기" 동기화 안내,
   "업데이트할 수 없습니다" 알림 등)는 실제 탭/페이지 창이 아니므로 감시
   대상에서 제외합니다. 이런 창은 보통 메인 브라우저 창을 소유자(owner)로
   둔 owned window라서, owner가 있는 창은 애초에 검사하지 않습니다(자세한
   내용은 _handle_window 참고). 혹시 이 구조적 필터로 못 거르는 경우를
   대비해, 알려진 문구도 화이트리스트에 이중 안전장치로 넣어둡니다.

종료 정책(하이브리드): WM_CLOSE로 정상 종료를 우선 시도하고, 일정 시간이
지나도 안 닫히는 경우에만 강제 종료로 승격합니다. 자세한 이유는
BrowserWatchdog 클래스 docstring을 참고하세요.
"""

import logging
import time
from typing import Callable, Dict, Iterable, Optional, Set

import psutil
import pystray
import win32con
import win32gui
import win32process
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

CHECK_INTERVAL_SEC = 1.5

# WM_CLOSE(정상 종료 요청)를 보낸 뒤 이 시간이 지나도 창이 살아있으면
# beforeunload 확인창 등에 막힌 것으로 보고 강제 종료로 승격한다.
GRACEFUL_WAIT_SEC = 3.0

# 강제 종료 직후, 같은 종류의 브라우저에 대해 추가 종료 시도를 쉬는 시간.
# 강제 종료로 인해 재실행된 브라우저가 세션 복구 파일을 쓰는 도중에 또
# 강제 종료를 당하면 프로필/세션 파일이 손상될 수 있어(브라우저 자체가
# 실행 불가 상태에 빠지는 문제로 이어짐), 그 위험을 줄이기 위한 장치다.
# 이 값이 위험을 없애주는 건 아니고 확률을 낮출 뿐이다.
KILL_COOLDOWN_SEC = 10.0

TARGET_BROWSERS = {"chrome.exe", "msedge.exe", "whale.exe", "firefox.exe"}

# 브라우저 실행 직후 초기 타이틀 예외 (정확히 일치할 때만 통과)
STARTUP_TITLES = {
    "google chrome", "chrome",
    "microsoft edge", "edge",
    "naver whale", "네이버 웨일", "whale",
}

# 최우선 차단 대상: Gemini(제미나이). 실질적으로 막아야 하는 핵심 대상이므로
# 표기 변형을 넉넉히 포함해 확실히 걸리도록 한다.
GEMINI_BLOCKED = [
    "gemini", "제미나이", "bard", "google gemini", "gemini.google.com",
]

# 그 외 보조 차단 키워드 (검색/동영상/기타 구글 딴짓 요소)
OTHER_BLOCKED = [
    "google 검색", "google search", "youtube", "유튜브",
    "google 번역", "google translate",
    "google 지도", "google maps", "google 어스", "google earth",
    "google play", "구글 플레이",
    "google 뉴스", "google news",
    "google 이미지", "google images",
    "google doodle", "구글 두들",
]

EXPLICIT_BLOCKED = GEMINI_BLOCKED + OTHER_BLOCKED

ALLOWED_KEYWORDS = [
    # 구글 메인 페이지 및 로그인 (로그인 후 원 사이트로 돌아오는 리다이렉트 보호용)
    "google", "google 계정", "google accounts", "로그인", "sign in",
    # 클래스룸
    "classroom", "클래스룸",
    # 드라이브 및 문서/스프레드시트/프레젠테이션
    "google drive", "구글 드라이브", "google docs", "google 문서",
    "google sheets", "google 스프레드시트", "google slides", "google 프레젠테이션",
    # 콜랩
    "colab", "colaboratory",
    # 브라우저 기본 창 / 로딩 순간 튕김 방지
    "새 탭", "new tab", "about:blank",
    "로딩 중", "loading", "연결 중", "connecting", "제목 없음", "untitled",
    # 도메인 주소 로딩 대응
    "drive.google.com", "classroom.google.com", "docs.google.com",
    "sheets.google.com", "slides.google.com", "colab.research.google.com",
    # 리로스쿨 (학교 시스템) - riroschool.kr 서브도메인은 전부 포함되도록
    # 최상위 도메인 문자열로 등록 (jinyangh.riroschool.kr 등도 자동 매칭됨)
    "리로스쿨", "riroschool", "riroschool.kr",
    # 브라우저 자체 시스템 다이얼로그 오탐 방지용 이중 안전장치.
    # owner 창 필터링(_handle_window)으로 대부분 걸러지지만, 못 걸러지는
    # 경우를 대비해 알려진 문구도 남겨둔다. (로그인 후 동기화 시작 안내,
    # 업데이트 실패 알림 등)
    "시작하기", "get started", "동기화", "sync",
    "업데이트", "update",
]


# ---------------------------------------------------------------------------
# 순수 판정 로직 (OS API에 의존하지 않아 단위 테스트가 쉬움)
# ---------------------------------------------------------------------------

class TitleClassifier:
    """창 제목 문자열만으로 종료 대상 여부를 판정한다."""

    def __init__(
        self,
        startup_titles: Iterable[str],
        blocked_keywords: Iterable[str],
        allowed_keywords: Iterable[str],
    ) -> None:
        self._startup_titles = {t.lower() for t in startup_titles}
        self._blocked_keywords = [k.lower() for k in blocked_keywords]
        self._allowed_keywords = [k.lower() for k in allowed_keywords]

    def should_close(self, title: str) -> bool:
        title_clean = title.strip().lower()
        if not title_clean:
            return False

        # 브라우저 초기 구동 타이틀은 통과
        if title_clean in self._startup_titles:
            return False

        # 블랙리스트에 걸리면 화이트리스트 여부와 무관하게 무조건 차단
        if any(kw in title_clean for kw in self._blocked_keywords):
            return True

        # 화이트리스트에 없으면 기본적으로 차단(기본 거부 정책)
        is_allowed = any(kw in title_clean for kw in self._allowed_keywords)
        return not is_allowed


# ---------------------------------------------------------------------------
# 창 감시 / 종료 처리
# ---------------------------------------------------------------------------

class BrowserWatchdog:
    """차단 대상 브라우저 창을 감시하고 종료한다.

    종료 정책은 2단계 하이브리드다.

    1) 우선 WM_CLOSE로 정상 종료를 시도한다. 브라우저가 스스로 종료 루틴을
       실행하게 해서 세션 파일을 안전하게 flush하고 "정상 종료"로 기록되게
       한다(다음 실행 시 "복원하시겠습니까?" 배너도 뜨지 않는다).
    2) graceful_wait_sec 이상 지나도 같은 창이 계속 남아있으면(beforeunload
       확인창 등에 막힌 것으로 판단) 그때만 프로세스를 강제 종료한다.
       강제 종료는 PID 단위로 이뤄지므로 같은 브라우저 인스턴스에 딸린 다른
       (정상) 창까지 함께 닫히고, exit_type이 Crashed로 남아 다음 실행 시
       복원 배너가 뜬다는 부작용이 있다. 그래서 이 경로는 예외적인 최후
       수단으로만 사용한다.

       강제 종료 직후에는 kill_cooldown_sec 동안 같은 종류의 브라우저에
       대해 추가 종료 시도를 하지 않는다(재실행 중인 브라우저가 세션 복구
       파일을 쓰는 도중에 또 강제 종료를 당해 프로필이 손상되는 것을
       예방하기 위함). 이 값은 위험을 없애는 게 아니라 줄여줄 뿐이다.

    notify_fn이 주어지면 두 시점에 각각 한 번씩(반복 스팸 없이) 알림을
    띄운다: (a) 정상 종료를 처음 시도한 순간(=유예 시작), (b) 유예 시간이
    지나 강제 종료로 승격한 순간(=쿨다운 시작). notify_fn 호출이 실패해도
    감시 동작에는 영향을 주지 않는다.
    """

    def __init__(
        self,
        classifier: TitleClassifier,
        target_browsers: Set[str],
        logger: logging.Logger,
        graceful_wait_sec: float = GRACEFUL_WAIT_SEC,
        kill_cooldown_sec: float = KILL_COOLDOWN_SEC,
        notify_fn: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.classifier = classifier
        self.target_browsers = target_browsers
        self.logger = logger
        self.graceful_wait_sec = graceful_wait_sec
        self.kill_cooldown_sec = kill_cooldown_sec
        self._notify_fn = notify_fn

        # hwnd -> WM_CLOSE를 처음 보낸 시각 (정상 종료 유예 기간 추적용)
        self._pending_close: Dict[int, float] = {}
        # proc_name -> 마지막 강제 종료 시각 (쿨다운 추적용)
        self._last_force_kill: Dict[str, float] = {}

    def run_once(self) -> None:
        """현재 열려 있는 모든 최상위 창을 한 번 스캔한다."""
        seen_hwnds: Set[int] = set()
        win32gui.EnumWindows(self._make_callback(seen_hwnds), None)

        # 이번 주기에 보이지 않은(이미 닫힌) 창의 대기 기록은 정리한다.
        # hwnd는 재사용될 수 있으므로 오래 남겨두면 안 된다.
        stale = [h for h in self._pending_close if h not in seen_hwnds]
        for h in stale:
            self._pending_close.pop(h, None)

    def _make_callback(self, seen_hwnds: Set[int]):
        def callback(hwnd, _extra):
            self._handle_window(hwnd, seen_hwnds)
        return callback

    def _handle_window(self, hwnd, seen_hwnds: Set[int]) -> None:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return

            # 실제 브라우저 창(탭이 있는 메인 창)이 아니라 브라우저가 자체적으로
            # 띄우는 시스템 다이얼로그/버블(로그인 완료 후 "시작하기" 동기화
            # 안내, "업데이트할 수 없습니다" 알림 등)은 건드리지 않는다.
            # 이런 창들은 대개 메인 브라우저 창을 소유자(owner)로 둔 owned
            # window이고, 실제 탭/페이지를 담은 메인 창은 owner가 없다(0).
            # window.open()으로 열리는 별도의 팝업 브라우저 창은 보통 owner가
            # 없는 독립된 창이라 이 필터에 걸리지 않고 정상적으로 검사된다.
            if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                return

            title = win32gui.GetWindowText(hwnd)
            if not title.strip():
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            # 열거 도중 창이 파괴되는 등 일시적인 win32 오류는 무시하고 계속 진행.
            return

        try:
            proc_name = psutil.Process(pid).name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return

        if proc_name not in self.target_browsers:
            return

        seen_hwnds.add(hwnd)

        if not self.classifier.should_close(title):
            self._pending_close.pop(hwnd, None)
            return

        if self._is_kill_on_cooldown(proc_name):
            # 최근에 이 브라우저 종류를 강제 종료했다면, 재실행 중인 복구
            # 프로세스를 방해하지 않도록 이번 주기는 그냥 넘어간다.
            return

        now = time.monotonic()
        first_seen = self._pending_close.get(hwnd)

        if first_seen is None:
            self.logger.info("차단됨 (정상 종료 시도): %s", title)
            self._pending_close[hwnd] = now
            self._close_window_gracefully(hwnd)
            self._notify(
                "차단 안내",
                f"'{title}' 창을 닫습니다. "
                f"{self.graceful_wait_sec:.0f}초 안에 닫히지 않으면 강제 종료됩니다.",
            )
            return

        if now - first_seen < self.graceful_wait_sec:
            return  # 정상 종료가 처리될 시간을 더 준다

        # 유예 시간이 지났는데도 살아있음 -> 정상 종료가 막힌 것으로 보고 승격
        self.logger.warning("정상 종료 실패로 판단, 강제 종료로 전환: %s", title)
        self._pending_close.pop(hwnd, None)
        self._force_kill(pid, proc_name)
        self._notify(
            "강제 종료됨",
            f"'{title}' 창이 정상적으로 닫히지 않아 브라우저를 강제 종료했습니다. "
            f"{self.kill_cooldown_sec:.0f}초간 재감시를 잠시 쉽니다.",
        )

    def _is_kill_on_cooldown(self, proc_name: str) -> bool:
        last_kill = self._last_force_kill.get(proc_name)
        return last_kill is not None and (time.monotonic() - last_kill) < self.kill_cooldown_sec

    def _notify(self, title: str, message: str) -> None:
        if self._notify_fn is None:
            return
        try:
            self._notify_fn(title, message)
        except Exception:
            # 알림 표시 실패가 감시 동작에 영향을 주면 안 되므로 로그만 남긴다
            self.logger.debug("알림 표시 실패", exc_info=True)

    @staticmethod
    def _close_window_gracefully(hwnd) -> None:
        """강제 종료(kill) 대신 WM_CLOSE 신호를 보내 정상 종료 처리."""
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass

    def _force_kill(self, pid: int, proc_name: str) -> None:
        """WM_CLOSE가 통하지 않을 때만 사용하는 최후 수단."""
        try:
            psutil.Process(pid).kill()
            self.logger.info("강제 종료 완료: pid=%s (%s)", pid, proc_name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        finally:
            # 종료 성공 여부와 무관하게, 재시도 폭주를 막기 위해 쿨다운을 갱신한다
            self._last_force_kill[proc_name] = time.monotonic()


# ---------------------------------------------------------------------------
# 트레이 아이콘
# ---------------------------------------------------------------------------

def create_tray_icon_image() -> Image.Image:
    """트레이에 표시할 64x64 파란색 상태 아이콘 이미지 생성"""
    image = Image.new("RGB", (64, 64), color=(37, 99, 235))
    draw = ImageDraw.Draw(image)
    draw.ellipse([16, 16, 48, 48], fill=(255, 255, 255))
    return image


def setup_tray_icon() -> pystray.Icon:
    """시스템 트레이 아이콘 생성 및 백그라운드 실행"""
    image = create_tray_icon_image()
    menu = pystray.Menu(
        pystray.MenuItem("🔒 수업 통제 프로그램 작동 중", lambda: None, enabled=False)
    )
    icon = pystray.Icon("StudentBlocker", image, "수업 통제 프로그램 (작동 중)", menu)
    icon.run_detached()
    return icon


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("student_blocker")

    tray_icon = setup_tray_icon()

    def notify(title: str, message: str) -> None:
        # 트레이 풍선/토스트 알림. 학생 화면에 논블로킹으로 표시되며
        # 클릭/확인 없이 몇 초 후 자동으로 사라진다.
        tray_icon.notify(message, title)

    classifier = TitleClassifier(STARTUP_TITLES, EXPLICIT_BLOCKED, ALLOWED_KEYWORDS)
    watchdog = BrowserWatchdog(classifier, TARGET_BROWSERS, logger, notify_fn=notify)

    logger.info("학생용 웹 통제 프로그램 동작 중...")
    try:
        while True:
            try:
                watchdog.run_once()
            except Exception:
                # 예기치 못한 예외로 감시 루프 자체가 죽지 않도록 기록만 하고 계속 진행
                logger.exception("감시 루프 처리 중 예외 발생")
            time.sleep(CHECK_INTERVAL_SEC)
    except KeyboardInterrupt:
        logger.info("종료 신호 수신, 프로그램을 종료합니다.")
    finally:
        tray_icon.stop()


if __name__ == "__main__":
    main()
