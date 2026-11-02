"""템플릿 필터. Django 한국어 로캘의 date:"D" 는 '월요일' 전체가 나와서 짧은 요일을 따로 만든다."""

from django import template

register = template.Library()

WEEKDAYS_KO = "월화수목금토일"


@register.filter
def wd(value):
    """date → '월'. 사용: {{ d|wd }}"""
    try:
        return WEEKDAYS_KO[value.weekday()]
    except AttributeError:
        return ""
