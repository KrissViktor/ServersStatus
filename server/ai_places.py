"""Russian place names in natural case, without guessing by cutting suffixes."""
from functools import lru_cache
import re
from .ai_web import WebError

PREPOSITIONS={'на','в','во','при','под','над','у','за','де','дель','ла','ле'}
ALIASES={'moscow':'Москва','спб':'Санкт-Петербург','saint petersburg':'Санкт-Петербург','st petersburg':'Санкт-Петербург','питер':'Санкт-Петербург'}

@lru_cache(maxsize=1)
def analyzer():
    try:
        import pymorphy3
        return pymorphy3.MorphAnalyzer(lang='ru')
    except (ImportError,OSError):raise WebError('Не установлен словарь городов. На Raspi обновите зависимости: .venv/bin/python -m pip install -r requirements.txt') from None


@lru_cache(maxsize=1024)
def normalize(value,case='loct'):
    value=' '.join(value.split())
    if value.casefold() in ALIASES:return ALIASES[value.casefold()]
    if not re.search('[а-яё]',value,re.I):return value
    parts=re.split(r'([\s-]+)',value);entries={};tail=False
    for index,word in enumerate(parts):
        if not word or re.fullmatch(r'[\s-]+',word):continue
        if index and word.casefold() in PREPOSITIONS:tail=True
        if tail or not re.search('[а-яё]',word,re.I):continue
        parses=[p for p in analyzer().parse(word) if p.is_known and p.tag.POS in ('NOUN','ADJF')]
        if not parses:continue
        # An adjective inside a place name should not be mistaken for a rare
        # homonymous settlement: Великих Луках -> Великие Луки, not Великое Луки.
        adjectives=[p for p in parses if p.tag.POS=='ADJF']
        if len(parts)>1 and adjectives:parses=adjectives
        entries[index]=max(parses,key=lambda p:('Geox' in p.tag,p.tag.case==case,p.score))
    nouns=[p for p in entries.values() if p.tag.POS=='NOUN']
    head=nouns[-1] if nouns else None
    for index,parsed in entries.items():
        features={'nomn'}
        number=head.tag.number if parsed.tag.POS=='ADJF' and head else parsed.tag.number
        if number:features.add(number)
        if parsed.tag.POS=='ADJF' and number!='plur':
            gender=head.tag.gender if head else parsed.tag.gender
            if gender in ('masc','femn','neut'):features.add(gender)
        result=parsed.inflect(features)
        if result:parts[index]=result.word.capitalize()
    # Unknown words retain their spelling; prepositional tails are proper-name
    # components (Ростов-на-Дону, Комсомольск-на-Амуре), not case errors.
    return ''.join(parts)


def city_input(query):
    match=re.search(r'(?:\bв|\bво|\bдля|\bin)\s+([^\n?!;,]+)',query,re.I)
    if not match:match=re.search(r'\b(?:погода|прогноз(?:\s+погоды)?|weather)\s+(?:(?:на\s+)?(?:завтра|сегодня|послезавтра|today|tomorrow)\s+)?([^\n?!;,]+)',query,re.I)
    if not match:raise WebError('Для прогноза укажите город, например: «Какая погода завтра в Мытищах?»')
    value=match[1]
    value=re.sub(r'^(?:городе|города|город|г\.)\s+','',value,flags=re.I)
    # Whitespace is essential: do not split Ростове-на-Дону at its internal на.
    value=re.split(r'\s+(?:завтра|сегодня|послезавтра|на|tomorrow|today|пожалуйста|сейчас|\d)',value,flags=re.I)[0].strip(' -.:')
    if value.casefold() in ('на','сегодня','завтра','послезавтра','today','tomorrow','на завтра','на сегодня','пожалуйста'):raise WebError('Для прогноза укажите город.')
    if not value or len(value)>80 or not re.fullmatch(r'[\w\s-]+',value):raise WebError('Не удалось определить город. Уточните его название.')
    case='gent' if re.search(r'\bдля\s+',match[0],re.I) else 'loct'
    return value,case
