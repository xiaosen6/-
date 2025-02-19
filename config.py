from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    KIMI_API_KEY: str = "sk-lATD3EkkaZHs7suqQUaxBgKFX8AK84S7sgaYTDwtVoD09YhK"
    KIMI_API_BASE: str = "https://api.moonshot.cn/v1"
    MODEL_NAME: str = "moonshot-v1-32k"

settings = Settings() 