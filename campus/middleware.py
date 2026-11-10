"""모든 응답에 'Lolypoly 앱이 만든 응답'이라는 표시를 붙인다 (D-055).

서비스 워커가 호스팅의 '깨어나는 중' 대기 화면을 우리 화면으로 착각해 저장하지 않도록,
X-Lolypoly 헤더가 있는 응답만 우리 앱 화면으로 본다. 개인정보·버전 정보는 넣지 않는다.
"""

APP_HEADER = "X-Lolypoly"


class AppMarkerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response[APP_HEADER] = "1"
        return response
