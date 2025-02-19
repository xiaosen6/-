import uvicorn
import os

if __name__ == "__main__":
    # 切换到Agent目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True) 
    