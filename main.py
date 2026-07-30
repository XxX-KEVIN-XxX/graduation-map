import os
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends, Body, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

# ========== 数据库相关导入 ==========
from sqlalchemy import create_engine, Column, Integer, String, Text, UniqueConstraint, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# ========== 初始化应用 ==========
app = FastAPI(title="毕业地图")
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ========== 数据库配置 ==========
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/users.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ========== 北京时间函数 ==========
def beijing_now():
    """返回北京时间字符串，格式 YYYY-MM-DD HH:MM"""
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M")

# ========== 数据库表模型 ==========
class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password = Column(String(100), nullable=False)
    name = Column(String(100), default="")
    country = Column(String(100), default="")
    province = Column(String(100), default="")
    city = Column(String(100), default="")
    district = Column(String(100), default="")
    message = Column(Text, default="")
    role = Column(String(20), default="user")

class LikeDB(Base):
    __tablename__ = "likes"
    id = Column(Integer, primary_key=True, index=True)
    from_username = Column(String(50), nullable=False, index=True)
    to_username = Column(String(50), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint('from_username', 'to_username', name='uq_from_to_like'),
    )

class CommentDB(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    to_username = Column(String(50), nullable=False, index=True)
    from_username = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(String(30), nullable=False)
    parent_id = Column(Integer, ForeignKey("comments.id"), nullable=True)
    parent = relationship("CommentDB", remote_side=[id], backref="replies")

# 启动时自动建表
Base.metadata.create_all(bind=engine)

# 数据库会话依赖
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ========== 初始化默认管理员 ==========
def init_default_admin():
    db = SessionLocal()
    admin_exist = db.query(UserDB).filter(UserDB.role == "admin").first()
    if not admin_exist:
        default_admin = UserDB(
            username="xuekecheng",
            password="123456",
            name="薛可成",
            role="admin"
        )
        second_admin = UserDB(
            username="liuchengyin",
            password="123456",
            name="柳成荫",
            role="admin"
        )
        db.add_all([default_admin, second_admin])
        db.commit()
        print("✅ 已创建默认管理员账号")
    db.close()
init_default_admin()

# ========== 请求数据模型 ==========
class LoginReq(BaseModel):
    username: str
    password: str

class UserEditReq(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    message: Optional[str] = None

class UserCreateReq(UserEditReq):
    username: str
    password: str
    role: str = "user"

class ChangePasswordReq(BaseModel):
    username: str
    old_password: str
    new_password: str
    confirm_password: str

class CommentCreateReq(BaseModel):
    content: str
    parent_id: Optional[int] = None

# ========== 页面路由 ==========
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/index", response_class=HTMLResponse)
async def map_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="change_password.html")

@app.get("/admin-users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin_users.html")

# ========== 登录接口 ==========
@app.post("/api/auth/login")
async def login(req: LoginReq, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == req.username).first()
    if not user or user.password != req.password:
        return {"code": 401, "msg": "账号或密码错误"}
    user_info = {
        "username": user.username,
        "name": user.name,
        "country": user.country,
        "province": user.province,
        "city": user.city,
        "district": user.district,
        "message": user.message,
        "role": user.role
    }
    return {"code": 200, "msg": "登录成功", "data": user_info}

# ========== 普通用户修改信息 ==========
@app.put("/api/user/self")
async def update_self(username: str, req: UserEditReq, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    update_data = req.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    new_info = {
        "username": user.username,
        "name": user.name,
        "country": user.country,
        "province": user.province,
        "city": user.city,
        "district": user.district,
        "message": user.message,
        "role": user.role
    }
    return {"code": 200, "msg": "保存成功", "data": new_info}

# ========== 修改密码 ==========
@app.api_route("/api/user/change-password", methods=["POST", "PUT"])
async def change_password(req: ChangePasswordReq, db: Session = Depends(get_db)):
    if not req.old_password or not req.new_password or not req.confirm_password:
        return {"code": 400, "msg": "所有密码项不能为空"}
    if req.new_password != req.confirm_password:
        return {"code": 400, "msg": "两次输入的新密码不一致"}
    if len(req.new_password) < 6:
        return {"code": 400, "msg": "新密码长度不能少于6位"}
    user = db.query(UserDB).filter(UserDB.username == req.username).first()
    if not user:
        return {"code": 404, "msg": "用户不存在"}
    if user.password != req.old_password:
        return {"code": 400, "msg": "原密码输入错误"}
    user.password = req.new_password
    db.commit()
    return {"code": 200, "msg": "密码修改成功，请重新登录"}

# ========== 管理员接口 ==========
@app.get("/api/admin/users")
async def get_all_users(admin_name: str, db: Session = Depends(get_db)):
    admin = db.query(UserDB).filter(UserDB.username == admin_name).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    users = db.query(UserDB).all()
    like_counts = {}
    all_likes = db.query(LikeDB).all()
    for record in all_likes:
        like_counts[record.to_username] = like_counts.get(record.to_username, 0) + 1

    user_list = []
    for user in users:
        user_list.append({
            "id": user.id,
            "username": user.username,
            "password": user.password,
            "name": user.name,
            "country": user.country,
            "province": user.province,
            "city": user.city,
            "district": user.district,
            "message": user.message,
            "role": user.role,
            "like_count": like_counts.get(user.username, 0)
        })
    return {"code": 200, "data": user_list}

@app.post("/api/admin/users")
async def add_user(admin_name: str, req: UserCreateReq, db: Session = Depends(get_db)):
    admin = db.query(UserDB).filter(UserDB.username == admin_name).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    exist_user = db.query(UserDB).filter(UserDB.username == req.username).first()
    if exist_user:
        return {"code": 400, "msg": "用户名已存在"}
    new_user = UserDB(**req.dict())
    db.add(new_user)
    db.commit()
    return {"code": 200, "msg": "用户添加成功"}

@app.put("/api/admin/users/{target_user}")
async def edit_user(admin_name: str, target_user: str, req: UserEditReq, db: Session = Depends(get_db)):
    admin = db.query(UserDB).filter(UserDB.username == admin_name).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    user = db.query(UserDB).filter(UserDB.username == target_user).first()
    if not user:
        return {"code": 404, "msg": "用户不存在"}
    update_data = req.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    return {"code": 200, "msg": "修改成功"}

@app.delete("/api/admin/users/{target_user}")
async def remove_user(admin_name: str, target_user: str, db: Session = Depends(get_db)):
    admin = db.query(UserDB).filter(UserDB.username == admin_name).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    if target_user == admin_name:
        return {"code": 400, "msg": "不能删除自己的账号"}
    user = db.query(UserDB).filter(UserDB.username == target_user).first()
    if not user:
        return {"code": 404, "msg": "用户不存在"}
    db.query(LikeDB).filter(
        (LikeDB.from_username == target_user) | (LikeDB.to_username == target_user)
    ).delete(synchronize_session=False)
    db.query(CommentDB).filter(
        (CommentDB.from_username == target_user) | (CommentDB.to_username == target_user)
    ).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    return {"code": 200, "msg": "删除成功"}

# ========== 点赞接口 ==========
@app.post("/api/like/{to_username}")
async def toggle_like(from_username: str, to_username: str, db: Session = Depends(get_db)):
    from_user = db.query(UserDB).filter(UserDB.username == from_username).first()
    if not from_user:
        return {"code": 404, "msg": "点赞者账号不存在"}
    if from_user.role == "teacher":
        return {"code": 403, "msg": "教师角色无点赞权限"}
    to_user = db.query(UserDB).filter(UserDB.username == to_username).first()
    if not to_user:
        return {"code": 404, "msg": "被点赞用户不存在"}
    if from_username == to_username:
        return {"code": 400, "msg": "不能给自己的留言点赞"}

    exist_like = db.query(LikeDB).filter(
        LikeDB.from_username == from_username,
        LikeDB.to_username == to_username
    ).first()

    if exist_like:
        db.delete(exist_like)
        liked = False
        msg = "取消点赞成功"
    else:
        new_like = LikeDB(from_username=from_username, to_username=to_username)
        db.add(new_like)
        liked = True
        msg = "点赞成功"

    db.commit()
    like_count = db.query(LikeDB).filter(LikeDB.to_username == to_username).count()
    return {
        "code": 200,
        "msg": msg,
        "data": {
            "liked": liked,
            "like_count": like_count
        }
    }

@app.get("/api/like/status/{to_username}")
async def get_like_status(to_username: str, from_username: Optional[str] = None, db: Session = Depends(get_db)):
    like_count = db.query(LikeDB).filter(LikeDB.to_username == to_username).count()
    liked = False
    if from_username:
        exist = db.query(LikeDB).filter(
            LikeDB.from_username == from_username,
            LikeDB.to_username == to_username
        ).first()
        liked = exist is not None
    return {
        "code": 200,
        "data": {
            "like_count": like_count,
            "liked": liked
        }
    }

# ========== 地图点位接口 ==========
@app.get("/api/map/points")
async def get_map_points(username: Optional[str] = None, db: Session = Depends(get_db)):
    users = db.query(UserDB).all()
    is_teacher = False
    if username:
        current_user = db.query(UserDB).filter(UserDB.username == username).first()
        if current_user and current_user.role == "teacher":
            is_teacher = True

    # 点赞数统计
    like_counts = {}
    all_likes = db.query(LikeDB).all()
    for record in all_likes:
        like_counts[record.to_username] = like_counts.get(record.to_username, 0) + 1

    # 评论数统计
    comment_counts = {}
    all_comments = db.query(CommentDB).all()
    for c in all_comments:
        comment_counts[c.to_username] = comment_counts.get(c.to_username, 0) + 1

    user_liked_set = set()
    if username and not is_teacher:
        my_likes = db.query(LikeDB).filter(LikeDB.from_username == username).all()
        user_liked_set = {record.to_username for record in my_likes}

    points = []
    for user in users:
        points.append({
            "username": user.username,
            "name": user.name,
            "country": user.country,
            "province": user.province,
            "city": user.city,
            "district": user.district,
            "message": user.message if not is_teacher else "",
            "like_count": like_counts.get(user.username, 0),
            "is_liked": user.username in user_liked_set,
            "comment_count": comment_counts.get(user.username, 0)   # 新增评论数
        })
    return {"code": 200, "data": points}

# ========== 评论接口（支持回复，使用北京时间） ==========
@app.post("/api/comment/{to_username}")
async def add_comment(
    to_username: str,
    from_username: str = Query(...),
    req: CommentCreateReq = Body(...),
    db: Session = Depends(get_db)
):
    from_user = db.query(UserDB).filter(UserDB.username == from_username).first()
    if not from_user:
        return {"code": 404, "msg": "评论者账号不存在"}
    if from_user.role == "teacher":
        return {"code": 403, "msg": "教师角色无评论权限"}

    to_user = db.query(UserDB).filter(UserDB.username == to_username).first()
    if not to_user:
        return {"code": 404, "msg": "被评论用户不存在"}

    parent_id = req.parent_id
    if parent_id is not None:
        parent_comment = db.query(CommentDB).filter(CommentDB.id == parent_id).first()
        if not parent_comment:
            return {"code": 404, "msg": "父评论不存在"}

    # 使用北京时间
    now = beijing_now()
    new_comment = CommentDB(
        to_username=to_username,
        from_username=from_username,
        content=req.content,
        created_at=now,
        parent_id=parent_id
    )
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)
    return {"code": 200, "msg": "评论成功", "data": {
        "id": new_comment.id,
        "from_username": new_comment.from_username,
        "from_name": from_user.name,
        "content": new_comment.content,
        "created_at": new_comment.created_at,
        "parent_id": new_comment.parent_id
    }}

@app.get("/api/comment/{to_username}")
async def get_comments(to_username: str, db: Session = Depends(get_db)):
    top_comments = db.query(CommentDB).filter(
        CommentDB.to_username == to_username,
        CommentDB.parent_id == None
    ).order_by(CommentDB.id.desc()).all()

    result = []
    for comment in top_comments:
        from_user = db.query(UserDB).filter(UserDB.username == comment.from_username).first()
        comment_data = {
            "id": comment.id,
            "from_username": comment.from_username,
            "from_name": from_user.name if from_user else comment.from_username,
            "content": comment.content,
            "created_at": comment.created_at,
            "parent_id": comment.parent_id,
            "replies": []
        }
        replies = db.query(CommentDB).filter(
            CommentDB.parent_id == comment.id
        ).order_by(CommentDB.id.asc()).all()
        for reply in replies:
            reply_user = db.query(UserDB).filter(UserDB.username == reply.from_username).first()
            comment_data["replies"].append({
                "id": reply.id,
                "from_username": reply.from_username,
                "from_name": reply_user.name if reply_user else reply.from_username,
                "content": reply.content,
                "created_at": reply.created_at,
                "parent_id": reply.parent_id
            })
        result.append(comment_data)
    return {"code": 200, "data": result}

@app.delete("/api/comment/{comment_id}")
async def delete_comment(comment_id: int, username: str, db: Session = Depends(get_db)):
    comment = db.query(CommentDB).filter(CommentDB.id == comment_id).first()
    if not comment:
        return {"code": 404, "msg": "评论不存在"}
    user = db.query(UserDB).filter(UserDB.username == username).first()
    if not user:
        return {"code": 404, "msg": "用户不存在"}
    if comment.from_username != username and user.role != "admin":
        return {"code": 403, "msg": "无删除权限"}
    db.query(CommentDB).filter(CommentDB.parent_id == comment_id).delete(synchronize_session=False)
    db.delete(comment)
    db.commit()
    return {"code": 200, "msg": "删除成功"}

# ========== 退出登录 ==========
@app.post("/api/auth/logout")
async def logout():
    return {"code": 200, "msg": "退出成功"}

# ========== 启动入口 ==========
if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)