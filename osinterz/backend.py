"""Public-source lookups. No account login, contact matching or breach databases."""
from __future__ import annotations
import ipaddress
import re
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit, urljoin
import dns.resolver
import phonenumbers
from phonenumbers import carrier, geocoder, timezone as phone_timezone
import requests
from bs4 import BeautifulSoup

TIMEOUT = 8
MAX_BYTES = 1_500_000


def public_host(host):
    addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Разрешены только публичные интернет-адреса.')
    return sorted({a[4][0] for a in addresses})


def normalize_site(value):
    raw = value.strip()
    parsed = urlsplit(raw if '://' in raw else 'https://' + raw)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Введите домен или http(s) URL без логина и пароля.')
    host = parsed.hostname.encode('idna').decode('ascii').lower().rstrip('.')
    try:
        ipaddress.ip_address(host)
        raise ValueError('Введите доменное имя, а не IP-адрес.')
    except ValueError as exc:
        if str(exc).startswith('Введите'):
            raise
    if len(host) > 253 or not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', host):
        raise ValueError('Некорректное доменное имя.')
    if parsed.port not in (None, 80, 443):
        raise ValueError('Поддерживаются стандартные порты 80 и 443.')
    return host, f'{parsed.scheme}://{host}' + (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')


def fetch(url, session=None):
    """Bounded downloads; recheck every redirect, disable environment proxies."""
    session = session or requests.Session()
    session.trust_env = False
    for _ in range(6):
        parsed = urlsplit(url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Недопустимый адрес перенаправления.')
        if parsed.port not in (None, 80, 443):
            raise ValueError('Недопустимый порт перенаправления.')
        public_host(parsed.hostname)
        with session.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True,
                         headers={'User-Agent': 'osinterz/1.0 (public metadata)'}) as response:
            if response.is_redirect or response.is_permanent_redirect:
                url = urljoin(url, response.headers['Location'])
                continue
            data = bytearray()
            for chunk in response.iter_content(16384):
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ValueError('Ответ превышает лимит 1,5 МБ.')
            response._content = bytes(data)
            response._content_consumed = True
            return response
    raise ValueError('Слишком много перенаправлений.')


def section(title, source, fn):
    try:
        return {'title': title, 'source': source, 'status': 'ok', 'data': fn()}
    except Exception as exc:
        return {'title': title, 'source': source, 'status': 'error', 'data': {'Ошибка': str(exc)[:350]}}


def dns_data(host):
    resolver = dns.resolver.Resolver()
    resolver.lifetime = TIMEOUT
    result = {}
    for kind in ('A', 'AAAA', 'MX', 'NS', 'TXT', 'CAA'):
        try:
            result[kind] = [str(r) for r in resolver.resolve(host, kind)]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            result[kind] = []
        except Exception as exc:
            result[kind] = 'Недоступно: ' + str(exc)[:150]
    return result


def tls_data(host):
    public_host(host)
    with socket.create_connection((host, 443), timeout=TIMEOUT) as sock:
        with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as conn:
            cert = conn.getpeercert()
            return {'Версия': conn.version(), 'Шифр': conn.cipher()[0],
                    'Выдан': cert.get('notBefore'), 'Действует до': cert.get('notAfter'),
                    'Издатель': dict(item for group in cert.get('issuer', ()) for item in group),
                    'Домены': [name for kind, name in cert.get('subjectAltName', ()) if kind == 'DNS']}


def http_data(url):
    response = fetch(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    meta = soup.find('meta', attrs={'name': re.compile('^description$', re.I)})
    headers = ('Server', 'Content-Type', 'Strict-Transport-Security', 'Content-Security-Policy',
               'X-Frame-Options', 'X-Content-Type-Options', 'Referrer-Policy')
    return {'URL': response.url, 'HTTP': response.status_code,
            'Заголовок': soup.title.get_text(' ', strip=True) if soup.title else 'Не указан',
            'Описание': meta.get('content', '') if meta else 'Не указано',
            **{name: response.headers.get(name, 'Не указан') for name in headers}}


def rdap_data(host):
    response = fetch('https://rdap.org/domain/' + host)
    response.raise_for_status()
    data = response.json()
    return {'Домен': data.get('ldhName'), 'Статусы': data.get('status', []),
            'События': [{e.get('eventAction', 'event'): e.get('eventDate')} for e in data.get('events', [])],
            'NS': [n.get('ldhName') for n in data.get('nameservers', [])],
            'Примечание': 'RDAP может не поддерживать зону или субдомен; персональные контакты не извлекаются.'}


def telegram_username(raw):
    value = raw.strip()
    if re.match(r'^https?://', value, re.I):
        parsed = urlsplit(value)
        if parsed.hostname not in ('t.me', 'telegram.me') or parsed.query or parsed.fragment:
            raise ValueError('Укажите @username или https://t.me/username.')
        value = parsed.path.strip('/')
    value = value.removeprefix('@')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', value):
        raise ValueError('Некорректный публичный Telegram-юзернейм.')
    return value


def telegram_data(username):
    response = fetch('https://t.me/' + username)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    title = soup.select_one('.tgme_page_title')
    description = soup.select_one('.tgme_page_description')
    extra = soup.select_one('.tgme_page_extra')
    if not title:
        raise ValueError('Публичная карточка недоступна; это не доказывает отсутствие аккаунта.')
    return {'Юзернейм': '@' + username, 'Название': title.get_text(' ', strip=True),
            'Описание': description.get_text(' ', strip=True) if description else 'Не опубликовано',
            'Публичная информация': extra.get_text(' ', strip=True) if extra else 'Не опубликована',
            'Ссылка': 'https://t.me/' + username,
            'Ограничение': 'Телефон, скрытые данные и личность владельца не определяются.'}


def phone_data(value):
    raw = value.strip()
    if not raw.startswith('+'):
        raise ValueError('Введите номер с кодом страны: +380…, +7…, +375…')
    number = phonenumbers.parse(raw, None)
    if number.extension:
        raise ValueError('Введите номер без добавочного номера.')
    valid = phonenumbers.is_valid_number(number)
    types = {0: 'Стационарный', 1: 'Мобильный', 2: 'Стационарный / мобильный', 3: 'Бесплатный', 4: 'Платный', 6: 'VoIP'}
    return {'E.164': phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164),
            'Международный': phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            'Возможный формат': phonenumbers.is_possible_number(number), 'Валиден по плану нумерации': valid,
            'Код страны': '+' + str(number.country_code), 'Страна ISO': phonenumbers.region_code_for_number(number) or 'Не определена',
            'Регион по префиксу': geocoder.description_for_number(number, 'ru') or 'Не определён',
            'Исходный оператор по префиксу': carrier.name_for_number(number, 'ru') or 'Не определён',
            'Часовые пояса по префиксу': list(phone_timezone.time_zones_for_number(number)) if valid else [],
            'Тип': types.get(phonenumbers.number_type(number), 'Другой / неизвестен'),
            'Ограничение': 'Офлайн-справочник libphonenumber. Перенос номера не учитывается. Не подтверждает активность, владельца или местоположение.'}


def investigate(mode, value):
    if mode == 'site':
        host, url = normalize_site(value)
        public_host(host)
        jobs = [('DNS-записи', 'Системный DNS-резолвер', lambda: dns_data(host)),
                ('HTTP и страница', url, lambda: http_data(url)),
                ('TLS-сертификат', host + ':443', lambda: tls_data(host)),
                ('Регистрация домена', 'https://rdap.org/domain/' + host, lambda: rdap_data(host))]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(section, *job) for job in jobs]
            sections = [future.result() for future in futures]
        target = host
    elif mode == 'telegram':
        target = telegram_username(value)
        sections = [section('Публичная карточка', 'https://t.me/' + target, lambda: telegram_data(target))]
    elif mode == 'phone':
        data = phone_data(value)
        target = data['E.164']
        sections = [{'title': 'План нумерации', 'source': 'libphonenumber ' + phonenumbers.__version__, 'status': 'ok', 'data': data}]
    else:
        raise ValueError('Неизвестный модуль.')
    return {'app': 'osinterz by abjectov', 'mode': mode, 'target': target,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'sections': sections}
