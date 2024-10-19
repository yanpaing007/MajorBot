from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str
   
    REF_ID: str = '916734478'
    TASKS_WITH_JOIN_CHANNEL: bool = False
    HOLD_COIN: list[int] = [550, 600]
    SWIPE_COIN: list[int] = [2000, 3000]
    SQUAD_ID: int = 1006503122
    USE_RANDOM_DELAY_IN_RUN: bool = True
    RANDOM_DELAY_IN_RUN: list[int] = [0, 15]
    FAKE_USERAGENT: bool = True
    SLEEP_TIME: list[int] = [7200, 10800]
    
    USE_PROXY_FROM_FILE: bool = True


settings = Settings()


