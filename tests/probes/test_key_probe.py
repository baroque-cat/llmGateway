# tests/probes/test_key_probe.py
import pytest
from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.services.probes.key_probe import KeyProbe

@pytest.mark.asyncio
async def test_key_probe_handles_invalid_key_error(mocker, test_config): # mocker - это фикстура
    # 1. Готовим "актеров"
    mock_db_manager = mocker.MagicMock() # Фальшивая база
    mock_client_factory = mocker.MagicMock() # Фальшивая фабрика клиентов
    
    # 2. Учим фальшивого провайдера возвращать ошибку
    mock_provider_instance = mocker.AsyncMock() # Асинхронная заглушка
    mock_provider_instance.check.return_value = CheckResult.fail(ErrorReason.INVALID_KEY)
    
    # 3. Перехватываем вызовы, которые мы не хотим выполнять
    # Когда кто-то вызовет get_provider, вернуть нашу заглушку
    mocker.patch('src.services.probes.key_probe.get_provider', return_value=mock_provider_instance)
    
    # 4. Создаем объект для теста с нашими фальшивками
    probe = KeyProbe(config=test_config, db_manager=mock_db_manager, client_factory=mock_client_factory)
    
    test_resource = {
        'provider_name': 'gemini_default',
        'key_value': 'fake_key',
        'model_name': 'gemini-1.0-pro',
        'key_id': 123
    }

    # 5. Запускаем тестируемый метод
    result = await probe._check_resource(test_resource)

    # 6. Проверяем результат (Assert)
    assert result.ok is False
    assert result.error_reason == ErrorReason.INVALID_KEY
    
    # Убедимся, что наш фальшивый провайдер был вызван с правильными аргументами
    mock_provider_instance.check.assert_awaited_once() 
