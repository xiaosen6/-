from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json
import os
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

router = APIRouter()

class KnowledgeItem(BaseModel):
    content: str

class GroupCreate(BaseModel):
    name: str

class MoveItem(BaseModel):
    group: str

# 确保知识库目录存在
os.makedirs("knowledge", exist_ok=True)
KNOWLEDGE_FILE = "knowledge/personal_kb.json"

def load_knowledge():
    try:
        if os.path.exists(KNOWLEDGE_FILE):
            with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):  # 处理旧格式数据
                    return {
                        "groups": [
                            {
                                "name": "未分组",
                                "items": data
                            }
                        ]
                    }
                return data
        return {"groups": [{"name": "未分组", "items": []}]}
    except Exception as e:
        logger.error(f"加载知识库失败: {str(e)}")
        return {"groups": [{"name": "未分组", "items": []}]}

def save_knowledge(knowledge_data):
    try:
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(knowledge_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存知识库失败: {str(e)}")
        return False

def get_next_id(knowledge_data):
    max_id = 0
    for group in knowledge_data["groups"]:
        for item in group["items"]:
            if item["id"] > max_id:
                max_id = item["id"]
    return max_id + 1

@router.post("/knowledge")
async def add_to_knowledge(item: KnowledgeItem):
    try:
        knowledge_data = load_knowledge()
        
        # 添加新的知识条目到未分组
        new_entry = {
            "content": item.content,
            "timestamp": datetime.now().isoformat(),
            "id": get_next_id(knowledge_data)
        }
        
        # 找到未分组并添加条目
        for group in knowledge_data["groups"]:
            if group["name"] == "未分组":
                group["items"].append(new_entry)
                break
        
        if save_knowledge(knowledge_data):
            logger.info(f"成功添加新知识条目: ID {new_entry['id']}")
            return {"status": "success", "message": "成功添加到知识库", "id": new_entry['id']}
        else:
            raise HTTPException(status_code=500, detail="保存知识库失败")
            
    except Exception as e:
        logger.error(f"添加知识条目时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加知识条目失败: {str(e)}")

@router.get("/knowledge")
async def get_knowledge():
    try:
        knowledge_data = load_knowledge()
        return {"items": knowledge_data["groups"]}
    except Exception as e:
        logger.error(f"获取知识库失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取知识库失败: {str(e)}")

@router.delete("/knowledge/{item_id}")
async def delete_knowledge_item(item_id: int):
    try:
        knowledge_data = load_knowledge()
        
        # 在所有分组中查找并删除指定ID的条目
        item_found = False
        original_items_count = {}
        new_items_count = {}
        
        for group in knowledge_data["groups"]:
            original_items_count[group["name"]] = len(group["items"])
            group["items"] = [item for item in group["items"] if item["id"] != item_id]
            new_items_count[group["name"]] = len(group["items"])
            if not item_found and original_items_count[group["name"]] > new_items_count[group["name"]]:
                item_found = True
                logger.info(f"在分组 {group['name']} 中找到并删除了条目 {item_id}")
        
        if not item_found:
            logger.warning(f"未找到ID为 {item_id} 的知识条目")
            raise HTTPException(status_code=404, detail="未找到指定的知识条目")
        
        if save_knowledge(knowledge_data):
            logger.info(f"成功删除知识条目: ID {item_id}")
            return {"status": "success", "message": "成功删除知识条目"}
        else:
            raise HTTPException(status_code=500, detail="保存知识库失败")
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"删除知识条目时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除知识条目失败: {str(e)}")

@router.post("/knowledge/groups")
async def create_group(group: GroupCreate):
    try:
        knowledge_data = load_knowledge()
        
        # 检查分组名是否已存在
        if any(g["name"] == group.name for g in knowledge_data["groups"]):
            raise HTTPException(status_code=400, detail="分组名已存在")
        
        # 创建新分组
        knowledge_data["groups"].append({
            "name": group.name,
            "items": []
        })
        
        if save_knowledge(knowledge_data):
            logger.info(f"成功创建分组: {group.name}")
            return {"status": "success", "message": "成功创建分组"}
        else:
            raise HTTPException(status_code=500, detail="保存知识库失败")
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"创建分组时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建分组失败: {str(e)}")

@router.delete("/knowledge/groups/{group_name}")
async def delete_group(group_name: str):
    try:
        knowledge_data = load_knowledge()
        
        if group_name == "未分组":
            raise HTTPException(status_code=400, detail="不能删除未分组")
        
        # 找到要删除的分组
        group_to_delete = None
        for group in knowledge_data["groups"]:
            if group["name"] == group_name:
                group_to_delete = group
                break
        
        if not group_to_delete:
            raise HTTPException(status_code=404, detail="未找到指定的分组")
        
        # 将该分组的条目移动到未分组
        ungrouped = next(g for g in knowledge_data["groups"] if g["name"] == "未分组")
        ungrouped["items"].extend(group_to_delete["items"])
        
        # 删除分组
        knowledge_data["groups"] = [g for g in knowledge_data["groups"] if g["name"] != group_name]
        
        if save_knowledge(knowledge_data):
            logger.info(f"成功删除分组: {group_name}")
            return {"status": "success", "message": "成功删除分组"}
        else:
            raise HTTPException(status_code=500, detail="保存知识库失败")
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"删除分组时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除分组失败: {str(e)}")

@router.post("/knowledge/{item_id}/move")
async def move_item(item_id: int, move: MoveItem):
    try:
        knowledge_data = load_knowledge()
        
        # 找到要移动的条目
        item_to_move = None
        source_group = None
        
        for group in knowledge_data["groups"]:
            for item in group["items"]:
                if item["id"] == item_id:
                    item_to_move = item
                    source_group = group
                    break
            if item_to_move:
                break
        
        if not item_to_move:
            raise HTTPException(status_code=404, detail="未找到指定的知识条目")
        
        # 找到目标分组
        target_group = None
        for group in knowledge_data["groups"]:
            if group["name"] == move.group:
                target_group = group
                break
        
        if not target_group:
            raise HTTPException(status_code=404, detail="未找到目标分组")
        
        # 移动条目
        source_group["items"].remove(item_to_move)
        target_group["items"].append(item_to_move)
        
        if save_knowledge(knowledge_data):
            logger.info(f"成功移动知识条目: ID {item_id} 到分组 {move.group}")
            return {"status": "success", "message": "成功移动知识条目"}
        else:
            raise HTTPException(status_code=500, detail="保存知识库失败")
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"移动知识条目时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"移动知识条目失败: {str(e)}") 