# Browser_block


학생용 브라우저 감시 프로그램 (보조 도구)

이 프로그램은 교사가 원격으로 학생 화면을 직접 감시하는 상황을 보조하는
도구입니다. 완벽한 차단 시스템이 아니라, 검색/검색결과 화면이나 Gemini(제미나이)
같은 대상이 "화면에 떠 있는 상태로 방치되는 것"을 자동으로 정리해 주는 역할을
합니다. 아래 네 가지는 의도적인 설계 결정이며, 버그가 아닙니다.

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

종료 정책(하이브리드): WM_CLOSE로 정상 종료를 우선 시도하고, 일정 시간이
지나도 안 닫히는 경우에만 강제 종료로 승격합니다. 자세한 이유는
BrowserWatchdog 클래스 docstring을 참고하세요.

이용 가능한 브라우저
   - 크롬(google chrome)
   - 엣지(microsoft edge)
   - 웨일(naver whale)

허용 가능한 사이트

1. 구글 메인 페이지 및 로그인 (로그인 후 원 사이트로 돌아오는 리다이렉트 보호용)
   - "google", "google 계정", "google accounts", "로그인", "sign in",
4. 클래스룸
   - "classroom", "클래스룸",
5. 드라이브 및 문서/스프레드시트/프레젠테이션
   - "google drive", "구글 드라이브", "google docs", "google 문서",
   - "google sheets", "google 스프레드시트", "google slides", "google 프레젠테이션",
6. 콜랩
   - "colab", "colaboratory",
7. 브라우저 기본 창 / 로딩 순간 튕김 방지
   - "새 탭", "new tab", "about:blank",
   - "로딩 중", "loading", "연결 중", "connecting", "제목 없음", "untitled",
8. 도메인 주소 로딩 대응
   - "drive.google.com", "classroom.google.com", "docs.google.com",
   - "sheets.google.com", "slides.google.com", "colab.research.google.com",
9. 리로스쿨 (학교 시스템)
   - riroschool.kr 서브도메인은 전부 포함되도록
   - 최상위 도메인 문자열로 등록 (jinyangh.riroschool.kr 등도 자동 매칭됨)
   - "리로스쿨", "riroschool", "riroschool.kr", "진양고 진로진학사이트"
