from unittest.mock import Mock, patch
import pytest
import backend as b

@pytest.mark.parametrize('value', ['https://user:pass@example.com', 'file:///etc/passwd', 'localhost', 'https://example.com:8080', 'https://a..com', 'https://127.0.0.1'])
def test_invalid_sites(value):
    with pytest.raises(ValueError):
        b.normalize_site(value)


def test_idn_and_url():
    host,url = b.normalize_site('https://пример.рф/path?q=one')
    assert host == 'xn--e1afmkfd.xn--p1ai'
    assert url.endswith('/path?q=one')

@pytest.mark.parametrize('ip', ['127.0.0.1','10.0.0.1','169.254.169.254','::1','192.168.1.1'])
def test_private_targets_rejected(ip):
    with patch.object(b.socket, 'getaddrinfo', return_value=[(None,None,None,None,(ip,0))]):
        with pytest.raises(ValueError):
            b.public_host('internal.example')

@pytest.mark.parametrize('value', ['https://evil.example/username', 'https://t.me/+invite', '@bad/user', 'https://t.me/name?start=abc'])
def test_invalid_telegram(value):
    with pytest.raises(ValueError):
        b.telegram_username(value)


def test_telegram_normalization():
    assert b.telegram_username('https://t.me/telegram') == 'telegram'
    assert b.telegram_username('@telegram') == 'telegram'


def test_phone_offline_and_explicit_country():
    with pytest.raises(ValueError):
        b.phone_data('0501234567')
    with patch.object(b, 'fetch', side_effect=AssertionError('network forbidden')):
        result = b.investigate('phone', '+12025550123')
    assert result['target'] == '+12025550123'
    assert result['sections'][0]['data']['Страна ISO'] == 'US'
    assert 'Владелец' not in result['sections'][0]['data']


def test_source_failure_is_preserved():
    result = b.section('TLS', 'example.com', lambda: 1/0)
    assert result['status'] == 'error'
    assert 'Ошибка' in result['data']


def test_redirect_revalidated():
    response = Mock()
    response.is_redirect = True
    response.headers = {'Location': 'http://127.0.0.1/'}
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = Mock()
    session.get.return_value = response
    with patch.object(b, 'public_host', side_effect=[['93.184.216.34'], ValueError('private')]) as check:
        with pytest.raises(ValueError, match='private'):
            b.fetch('https://example.com', session)
    assert check.call_count == 2
    session.get.assert_called_once()


def test_public_telegram_fixture():
    response = Mock()
    response.text = '<div class="tgme_page_title">Public channel</div><div class="tgme_page_description">News</div>'
    with patch.object(b, 'fetch', return_value=response):
        result = b.telegram_data('sample_channel')
    assert result['Название'] == 'Public channel'
    assert result['Описание'] == 'News'


def test_unavailable_telegram_is_not_absence():
    response = Mock()
    response.text = '<html>Unavailable</html>'
    with patch.object(b, 'fetch', return_value=response):
        with pytest.raises(ValueError, match='не доказывает'):
            b.telegram_data('sample_channel')
