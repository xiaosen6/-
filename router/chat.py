from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
from config import settings
import asyncio
from typing import List, Dict, Any, Optional
import logging
import time
import json
from datetime import datetime
import random

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

router = APIRouter()

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    stream: Optional[bool] = False

class ChatResponse(BaseModel):
    response: str

# 请求限制配置
last_request_time = 0
MIN_REQUEST_INTERVAL = 3.0  # 增加最小请求间隔到3秒
MAX_RETRIES = 5  # 增加最大重试次数
INITIAL_RETRY_DELAY = 3.0  # 增加初始重试延迟
MAX_JITTER = 1.0  # 最大随机抖动时间

async def call_kimi_api_with_retry(messages: List[Dict[str, Any]], max_retries: int = MAX_RETRIES, initial_delay: float = INITIAL_RETRY_DELAY):
    global last_request_time
    
    # 检查请求间隔
    current_time = time.time()
    time_since_last_request = current_time - last_request_time
    
    if time_since_last_request < MIN_REQUEST_INTERVAL:
        wait_time = MIN_REQUEST_INTERVAL - time_since_last_request + random.uniform(0, MAX_JITTER)
        logger.info(f"请求太频繁，等待 {wait_time:.2f} 秒")
        await asyncio.sleep(wait_time)
    
    headers = {
        "Authorization": f"Bearer {settings.KIMI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": settings.MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
        "stream": False,
        "max_tokens": 1000
    }
    
    logger.info(f"准备发送请求，消息数量: {len(messages)}")
    
    last_error = None
    for attempt in range(max_retries):
        try:
            # 指数退避 + 随机抖动
            retry_delay = initial_delay * (2 ** attempt) + random.uniform(0, MAX_JITTER)
            if attempt > 0:
                logger.info(f"等待 {retry_delay:.2f} 秒后进行第 {attempt + 1} 次重试")
                await asyncio.sleep(retry_delay)
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"开始第 {attempt + 1}/{max_retries} 次尝试")
                
                response = await client.post(
                    f"{settings.KIMI_API_BASE}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
                
                last_request_time = time.time()
                
                if response.status_code == 429:
                    logger.warning(f"遇到频率限制，尝试次数: {attempt + 1}")
                    if attempt < max_retries - 1:  # 如果不是最后一次尝试
                        continue
                    else:
                        raise HTTPException(
                            status_code=429,
                            detail="服务器繁忙，请稍后再试"
                        )
                
                response_json = response.json()
                logger.info(f"收到响应，状态码: {response.status_code}")
                
                if response.status_code != 200:
                    error_detail = response_json.get('error', {}).get('message', '未知错误')
                    logger.error(f"API错误: {error_detail}")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"API调用失败: {error_detail}"
                    )
                
                # 验证响应格式
                if not isinstance(response_json, dict):
                    raise HTTPException(status_code=500, detail="API返回格式错误")
                
                choices = response_json.get('choices', [])
                if not choices or not isinstance(choices, list):
                    raise HTTPException(status_code=500, detail="API返回内容为空")
                
                first_choice = choices[0]
                if not isinstance(first_choice, dict):
                    raise HTTPException(status_code=500, detail="API返回格式错误")
                
                message = first_choice.get('message', {})
                if not isinstance(message, dict):
                    raise HTTPException(status_code=500, detail="API返回格式错误")
                
                content = message.get('content')
                if not content:
                    raise HTTPException(status_code=500, detail="API返回内容为空")
                
                logger.info("成功处理响应")
                return response_json
                
        except httpx.TimeoutException as e:
            logger.error(f"请求超时: {str(e)}")
            last_error = HTTPException(status_code=504, detail=f"请求超时，请稍后重试")
        except httpx.RequestError as e:
            logger.error(f"请求错误: {str(e)}")
            last_error = HTTPException(status_code=500, detail=f"网络请求错误: {str(e)}")
        except Exception as e:
            logger.error(f"意外错误: {str(e)}")
            if isinstance(e, HTTPException):
                last_error = e
            else:
                last_error = HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")
    
    logger.error(f"所有重试都失败了，最后的错误: {str(last_error)}")
    raise last_error or HTTPException(status_code=429, detail="服务器繁忙，请稍后重试")

async def stream_kimi_response(messages: List[Dict[str, Any]]):
    headers = {
        "Authorization": f"Bearer {settings.KIMI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": settings.MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
        "stream": True,
        "max_tokens": 1000
    }

    retries = 0
    max_retries = 3
    base_delay = 1.0

    while True:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream(
                    'POST',
                    f"{settings.KIMI_API_BASE}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0
                ) as response:
                    if response.status_code == 429:
                        retries += 1
                        if retries > max_retries:
                            raise HTTPException(
                                status_code=429,
                                detail="服务器繁忙，请稍后重试"
                            )
                        
                        # 解析等待时间
                        try:
                            error_body = await response.aread()
                            error_json = json.loads(error_body)
                            wait_time = int(error_json.get('error', {}).get('message', '').split('after ')[1].split(' seconds')[0])
                        except:
                            wait_time = base_delay * (2 ** (retries - 1))  # 指数退避
                        
                        logger.info(f"遇到频率限制，等待 {wait_time} 秒后重试 ({retries}/{max_retries})")
                        yield json.dumps({"response": f"\n[正在等待API限制解除，{wait_time}秒后自动重试...]\n"}, ensure_ascii=False) + '\n'
                        await asyncio.sleep(wait_time)
                        continue

                    if response.status_code != 200:
                        error_detail = await response.aread()
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=f"API调用失败: {error_detail.decode()}"
                        )

                    logger.info("开始接收流式响应")
                    buffer = ""
                    async for chunk in response.aiter_bytes():
                        buffer += chunk.decode()
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            if line.strip():
                                try:
                                    # 处理 data: 前缀
                                    if line.startswith('data: '):
                                        line = line[6:]  # 移除 'data: ' 前缀
                                    if line == '[DONE]':
                                        continue
                                        
                                    data = json.loads(line)
                                    if 'choices' in data and len(data['choices']) > 0:
                                        delta = data['choices'][0].get('delta', {})
                                        if 'content' in delta:
                                            content = delta['content']
                                            if content:
                                                logger.debug(f"发送内容: {content}")
                                                yield json.dumps({"response": content}, ensure_ascii=False) + '\n'
                                except json.JSONDecodeError as e:
                                    logger.error(f"JSON解析错误: {str(e)}, 原始数据: {line}")
                                    continue
                                except Exception as e:
                                    logger.error(f"处理流式响应时出错: {str(e)}")
                                    continue
                    logger.info("流式响应接收完成")
                    break  # 成功完成，退出重试循环

        except Exception as e:
            logger.error(f"流式请求出错: {str(e)}")
            raise HTTPException(status_code=500, detail=f"流式请求出错: {str(e)}")

@router.post("/chat", response_model=None)
async def chat(request: ChatRequest):
    try:
        messages = [msg.dict() for msg in request.messages]
        logger.info(f"收到聊天请求，消息数量: {len(messages)}")
        
        if request.stream:
            return StreamingResponse(
                stream_kimi_response(messages),
                media_type="text/event-stream"
            )
        else:
            response = await call_kimi_api_with_retry(messages)
            assistant_message = response["choices"][0]["message"]["content"]
            if not assistant_message:
                logger.error("收到空响应")
                raise HTTPException(status_code=500, detail="获取到空回复")
                
            logger.info("成功处理聊天请求")
            return ChatResponse(response=assistant_message)
            
    except HTTPException as he:
        logger.error(f"HTTP异常: {str(he)}")
        raise he
    except Exception as e:
        logger.error(f"处理请求时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理请求时出错: {str(e)}") 