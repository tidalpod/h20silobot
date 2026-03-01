"""Entity bank account management — CRUD for entities + Plaid Link for bank accounts"""

import logging
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import EntityConfig, EntityBankAccount, Property
from webapp.auth.dependencies import get_current_user
from webapp.services import plaid_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["entity-accounts"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/bank-accounts", response_class=HTMLResponse)
async def bank_accounts_page(request: Request):
    """Entity bank accounts management page."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get all entities with their bank accounts
        result = await session.execute(
            select(EntityConfig)
            .options(selectinload(EntityConfig.bank_accounts))
            .order_by(EntityConfig.entity_name)
        )
        entities = result.scalars().all()

        # Count properties per entity
        property_counts = {}
        for entity in entities:
            count_result = await session.execute(
                select(func.count(Property.id))
                .where(Property.entity == entity.entity_name)
                .where(Property.is_active == True)
            )
            property_counts[entity.id] = count_result.scalar() or 0

    return templates.TemplateResponse(
        "payments/bank_accounts.html",
        {
            "request": request,
            "user": user,
            "entities": entities,
            "property_counts": property_counts,
        },
    )


@router.post("/bank-accounts/entities/create")
async def create_entity(
    request: Request,
    entity_name: str = Form(...),
    owner_name: str = Form(None),
    email: str = Form(None),
    phone: str = Form(None),
    mailing_address: str = Form(None),
):
    """Create a new entity."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        entity = EntityConfig(
            entity_name=entity_name,
            owner_name=owner_name or None,
            email=email or None,
            phone=phone or None,
            mailing_address=mailing_address or None,
        )
        session.add(entity)

    return RedirectResponse(url="/payments/bank-accounts", status_code=303)


@router.post("/bank-accounts/entities/{entity_id}/update")
async def update_entity(
    request: Request,
    entity_id: int,
    entity_name: str = Form(...),
    owner_name: str = Form(None),
    email: str = Form(None),
    phone: str = Form(None),
    mailing_address: str = Form(None),
):
    """Update an entity."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(EntityConfig).where(EntityConfig.id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if not entity:
            return RedirectResponse(url="/payments/bank-accounts", status_code=303)

        entity.entity_name = entity_name
        entity.owner_name = owner_name or None
        entity.email = email or None
        entity.phone = phone or None
        entity.mailing_address = mailing_address or None

    return RedirectResponse(url="/payments/bank-accounts", status_code=303)


@router.post("/bank-accounts/entities/{entity_id}/delete")
async def delete_entity(request: Request, entity_id: int):
    """Delete an entity and its bank accounts."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(EntityConfig)
            .where(EntityConfig.id == entity_id)
            .options(selectinload(EntityConfig.bank_accounts))
        )
        entity = result.scalar_one_or_none()
        if not entity:
            return RedirectResponse(url="/payments/bank-accounts", status_code=303)

        # Unlink Plaid items for all bank accounts
        for acct in entity.bank_accounts:
            try:
                await plaid_service.remove_item(acct.plaid_access_token)
            except Exception:
                pass  # Best effort unlink

        await session.delete(entity)

    return RedirectResponse(url="/payments/bank-accounts", status_code=303)


@router.get("/bank-accounts/add", response_class=HTMLResponse)
async def add_bank_account_page(request: Request, entity_id: int = None):
    """Add bank account page — select entity, then connect via Plaid or enter manually."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(EntityConfig).order_by(EntityConfig.entity_name)
        )
        entities = result.scalars().all()

    return templates.TemplateResponse(
        "payments/add_bank_account.html",
        {
            "request": request,
            "user": user,
            "entities": entities,
            "selected_entity_id": entity_id,
        },
    )


@router.post("/bank-accounts/manual")
async def add_manual_bank_account(
    request: Request,
    entity_id: int = Form(...),
    institution_name: str = Form(...),
    account_name: str = Form(...),
    account_type: str = Form(...),
    routing_number: str = Form(...),
    account_number: str = Form(...),
):
    """Save a manually entered bank account."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Get last 4 digits as mask
    account_mask = account_number[-4:] if len(account_number) >= 4 else account_number

    async with get_session() as session:
        # Check if first account for this entity
        count_result = await session.execute(
            select(func.count(EntityBankAccount.id))
            .where(EntityBankAccount.entity_id == entity_id)
            .where(EntityBankAccount.is_active == True)
        )
        existing_count = count_result.scalar() or 0

        bank_account = EntityBankAccount(
            entity_id=entity_id,
            institution_name=institution_name,
            account_name=account_name,
            account_type=account_type,
            routing_number=routing_number,
            account_number=account_number,
            account_mask=account_mask,
            is_manual=True,
            is_default=(existing_count == 0),
        )
        session.add(bank_account)

    return RedirectResponse(url="/payments/bank-accounts", status_code=303)


@router.post("/bank-accounts/link-token")
async def get_link_token(request: Request):
    """Get a Plaid Link token for an entity."""
    logger.info("=== Entity link-token route hit ===")
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    entity_id = data.get("entity_id")
    logger.info(f"Link token request for entity_id={entity_id}")
    if not entity_id:
        return JSONResponse({"error": "entity_id required"}, status_code=400)

    async with get_session() as session:
        result = await session.execute(
            select(EntityConfig).where(EntityConfig.id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if not entity:
            return JSONResponse({"error": "Entity not found"}, status_code=404)

        link_result = await plaid_service.create_entity_link_token(
            entity_id=entity.id,
            entity_name=entity.entity_name,
        )

    if "error" in link_result:
        return JSONResponse({"error": link_result["error"]}, status_code=500)

    return JSONResponse({"link_token": link_result["link_token"]})


@router.post("/bank-accounts/link-complete")
async def link_complete(request: Request):
    """Exchange Plaid public token and save entity bank account."""
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    public_token = data.get("public_token")
    entity_id = data.get("entity_id")
    account_id = data.get("account_id")

    if not all([public_token, entity_id]):
        return JSONResponse({"error": "public_token and entity_id required"}, status_code=400)

    # Exchange public token
    exchange_result = await plaid_service.exchange_public_token(public_token)
    if "error" in exchange_result:
        return JSONResponse({"error": exchange_result["error"]}, status_code=500)

    access_token = exchange_result["access_token"]
    item_id = exchange_result["item_id"]

    # Get account details
    accounts_result = await plaid_service.get_accounts(access_token)
    if "error" in accounts_result:
        return JSONResponse({"error": accounts_result["error"]}, status_code=500)

    accounts = accounts_result.get("accounts", [])
    institution_name = accounts_result.get("institution_name", "")

    # Pick the selected account, or first one
    selected_account = None
    if account_id:
        selected_account = next((a for a in accounts if a["account_id"] == account_id), None)
    if not selected_account and accounts:
        selected_account = accounts[0]

    if not selected_account:
        return JSONResponse({"error": "No accounts found"}, status_code=400)

    async with get_session() as session:
        # Check if this is the first account for this entity (make it default)
        count_result = await session.execute(
            select(func.count(EntityBankAccount.id))
            .where(EntityBankAccount.entity_id == entity_id)
            .where(EntityBankAccount.is_active == True)
        )
        existing_count = count_result.scalar() or 0

        bank_account = EntityBankAccount(
            entity_id=entity_id,
            plaid_access_token=access_token,
            plaid_item_id=item_id,
            plaid_account_id=selected_account["account_id"],
            account_name=selected_account.get("name") or selected_account.get("official_name", ""),
            account_mask=selected_account.get("mask", ""),
            institution_name=institution_name,
            account_type=selected_account.get("subtype") or selected_account.get("type", ""),
            is_default=(existing_count == 0),
        )
        session.add(bank_account)

    return JSONResponse({"success": True})


@router.post("/bank-accounts/accounts/{account_id}/set-default")
async def set_default_account(request: Request, account_id: int):
    """Set a bank account as the default for its entity."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(EntityBankAccount).where(EntityBankAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            return RedirectResponse(url="/payments/bank-accounts", status_code=303)

        # Clear default on all accounts for this entity
        all_result = await session.execute(
            select(EntityBankAccount)
            .where(EntityBankAccount.entity_id == account.entity_id)
        )
        for acct in all_result.scalars().all():
            acct.is_default = (acct.id == account_id)

    return RedirectResponse(url="/payments/bank-accounts", status_code=303)


@router.post("/bank-accounts/accounts/{account_id}/unlink")
async def unlink_account(request: Request, account_id: int):
    """Unlink (deactivate) a bank account."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(EntityBankAccount).where(EntityBankAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            return RedirectResponse(url="/payments/bank-accounts", status_code=303)

        # Remove from Plaid
        try:
            await plaid_service.remove_item(account.plaid_access_token)
        except Exception:
            pass  # Best effort

        account.is_active = False
        account.is_default = False

        # If this was default, promote another active account
        if True:  # Always check for a new default
            next_result = await session.execute(
                select(EntityBankAccount)
                .where(EntityBankAccount.entity_id == account.entity_id)
                .where(EntityBankAccount.is_active == True)
                .where(EntityBankAccount.id != account_id)
                .limit(1)
            )
            next_account = next_result.scalar_one_or_none()
            if next_account:
                next_account.is_default = True

    return RedirectResponse(url="/payments/bank-accounts", status_code=303)
