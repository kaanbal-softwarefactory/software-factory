from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.defaults import JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.models import Token, TokenData, User, UserInDB
from app.db import get_db
from app.services.activity_log import activity_log, CATEGORY_AUTH

router = APIRouter()

# Security Config
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = JWT_ALGORITHM

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Un token personal (kbl_...) no es un JWT: identifica a su dueño por la
    # tabla de tokens. Resolverlo aquí hace que valga en toda la API sin tocar
    # cada router; el alcance del token lo aplica el middleware de acceso.
    from app.services import access, access_store

    if access.looks_like_token(token):
        principal = await access_store.principal_from_token(token)
        if principal is None:
            raise credentials_exception
        user = await get_db().users.find_one({"username": principal.username})
        if user is None:
            raise credentials_exception
        return User(**user)

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    db = get_db()
    user = await db.users.find_one({"username": token_data.username})
    if user is None:
        raise credentials_exception
    return User(**user)


async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    db = get_db()
    user_dict = await db.users.find_one({"username": form_data.username})
    
    if not user_dict or not verify_password(form_data.password, user_dict['hashed_password']):
        await activity_log.log(
            "auth.login.failed",
            category=CATEGORY_AUTH,
            level="warn",
            actor=form_data.username,
            detail={"reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_dict["username"], "role": user_dict.get("role", "user")},
        expires_delta=access_token_expires
    )
    await activity_log.log(
        "auth.login.success",
        category=CATEGORY_AUTH,
        actor=user_dict["username"],
        detail={"role": user_dict.get("role", "user")},
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/signup", status_code=201)
async def create_user(user: UserInDB):
    """
    Create a new user.
    - If no users exist in DB: allows bootstrap (first admin user)
    - Otherwise: requires authentication (only logged-in users can create accounts)
    """
    db = get_db()
    user_count = await db.users.count_documents({})

    # If users already exist, require authentication
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signup disabled. Use an admin account to create new users."
        )

    existing = await db.users.find_one({"username": user.username})
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    user_data = user.model_dump()
    user_data["hashed_password"] = get_password_hash(user_data["hashed_password"])
    user_data["role"] = "admin"  # First user is always admin
    
    await db.users.insert_one(user_data)
    await activity_log.log(
        "auth.bootstrap_admin.created",
        category=CATEGORY_AUTH,
        actor=user.username,
        detail={"role": "admin"},
    )
    return {"username": user.username, "message": "Admin user created (bootstrap)"}


@router.post("/users", status_code=201)
async def create_user_admin(user: UserInDB, current_user: User = Depends(get_current_active_user)):
    """Create a new user (requires authentication)"""
    db = get_db()
    existing = await db.users.find_one({"username": user.username})
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    user_data = user.model_dump()
    user_data["hashed_password"] = get_password_hash(user_data["hashed_password"])
    if "role" not in user_data or not user_data.get("role"):
        user_data["role"] = "user"
    
    await db.users.insert_one(user_data)
    await activity_log.log(
        "auth.user.created",
        category=CATEGORY_AUTH,
        actor=current_user.username,
        target=user.username,
        detail={"role": user_data.get("role", "user")},
    )
    return {"username": user.username, "message": "User created"}


@router.get("/me")
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Get current user info"""
    return {"username": current_user.username, "email": current_user.email, "role": current_user.role}
