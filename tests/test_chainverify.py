from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

from marco_bot import chainverify
from marco_bot.db import _ensure_transaction_columns_sync

DEPOSIT_EVM = "0x4ea801303C12Bf628E6c9dd661962eF7b36C9301"
DEPOSIT_TRON = "TX471pFdCnad1X5Xx5dRV4DzcpbcpVQo6W"
DEPOSIT_BTC = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
USDT_BSC_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
USDT_TRON_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
EVM_HASH = "0x" + "ab" * 32
TRON_HASH = "ab" * 32
BTC_HASH = "cd" * 32


def settings(evm_key: str | None = "KEY", tron_key: str | None = "TKEY"):
    return SimpleNamespace(etherscan_api_key=evm_key, trongrid_api_key=tron_key, infura_api_key=None, infura_url=None)


def run(coro):
    return asyncio.run(coro)


def topic_address(address: str) -> str:
    return "0x" + "0" * 24 + address.lower().removeprefix("0x")


def evm_fetch(*, tx=None, receipt=None, tip: str = "0x104"):
    async def fetch(url, params, headers, json_body=None):
        assert params.get("module") == "proxy"
        action = params.get("action")
        if action == "eth_getTransactionByHash":
            return {"result": tx}
        if action == "eth_getTransactionReceipt":
            return {"result": receipt}
        if action == "eth_blockNumber":
            return {"result": tip}
        raise AssertionError(f"unexpected Etherscan action: {action}")

    return fetch


def evm_token_receipt(logs, status: str = "0x1", block: str = "0xf0"):
    return {"status": status, "blockNumber": block, "logs": logs}


def usdt_bsc_log(to_address: str, amount: int) -> dict:
    return {
        "address": USDT_BSC_CONTRACT,
        "topics": [chainverify.TRANSFER_TOPIC, "0x" + "11" * 32, topic_address(to_address)],
        "data": hex(amount),
    }


# ---------------------------------------------------------------- hash helpers

def test_normalize_tx_hash_evm_prefixes_bare_hex():
    assert chainverify.normalize_tx_hash("ab" * 32, "BEP20") == "0x" + "ab" * 32


def test_normalize_tx_hash_evm_keeps_prefixed():
    assert chainverify.normalize_tx_hash(EVM_HASH.upper().replace("0X", "0x"), "ERC20") == EVM_HASH


def test_normalize_tx_hash_tron_strips_prefix():
    assert chainverify.normalize_tx_hash("0x" + TRON_HASH, "TRC20") == TRON_HASH


def test_normalize_tx_hash_rejects_garbage():
    assert chainverify.normalize_tx_hash("not a hash", "BEP20") is None
    assert chainverify.normalize_tx_hash("ab" * 10, "TRC20") is None


# ---------------------------------------------------------------- support matrix

def test_support_status_ok_for_registered_assets():
    assert chainverify.support_status(settings(), "USDT", "BEP20", DEPOSIT_EVM)[0]
    assert chainverify.support_status(settings(), "USDT", "ERC20", DEPOSIT_EVM)[0]
    assert chainverify.support_status(settings(), "ETH", "ERC20", DEPOSIT_EVM)[0]
    assert chainverify.support_status(settings(), "USDT", "TRC20", DEPOSIT_TRON)[0]
    assert chainverify.support_status(settings(), "BTC", "BTC", DEPOSIT_BTC)[0]


def test_support_status_needs_no_key_thanks_to_public_rpc():
    assert chainverify.support_status(settings(evm_key=None), "USDT", "BEP20", DEPOSIT_EVM)[0]


def test_support_status_blocks_unsafe_cases():
    assert not chainverify.support_status(settings(), "USDT", "BEP20", "CONFIGURE_USDT_BEP20_ADDRESS")[0]
    assert not chainverify.support_status(settings(), "ETH", "TRC20", DEPOSIT_TRON)[0]
    assert not chainverify.support_status(settings(), "DOGE", "BTC", DEPOSIT_BTC)[0]
    assert not chainverify.support_status(settings(), "USDT", "SOL", "anything")[0]


# ---------------------------------------------------------------- EVM

def test_evm_usdt_bsc_verified():
    tx = {"hash": EVM_HASH, "to": USDT_BSC_CONTRACT, "blockNumber": "0xf0", "value": "0x0"}
    receipt = evm_token_receipt([usdt_bsc_log(DEPOSIT_EVM, 100 * 10**18)])
    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=evm_fetch(tx=tx, receipt=receipt)))
    assert result.status == chainverify.STATUS_VERIFIED
    assert result.amount == Decimal("100")
    assert result.confirmations == 21
    assert "bscscan.com" in (result.explorer_url or "")


def test_evm_usdt_amount_too_low_fails():
    tx = {"hash": EVM_HASH, "to": USDT_BSC_CONTRACT, "blockNumber": "0xf0", "value": "0x0"}
    receipt = evm_token_receipt([usdt_bsc_log(DEPOSIT_EVM, 50 * 10**18)])
    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=evm_fetch(tx=tx, receipt=receipt)))
    assert result.status == chainverify.STATUS_FAILED
    assert "50" in result.detail


def test_evm_transfer_to_someone_else_fails():
    tx = {"hash": EVM_HASH, "to": USDT_BSC_CONTRACT, "blockNumber": "0xf0", "value": "0x0"}
    other = "0x1111111111111111111111111111111111111111"
    receipt = evm_token_receipt([usdt_bsc_log(other, 100 * 10**18)])
    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=evm_fetch(tx=tx, receipt=receipt)))
    assert result.status == chainverify.STATUS_FAILED
    assert "no USDT transfer" in result.detail


def test_evm_reverted_tx_fails():
    tx = {"hash": EVM_HASH, "to": USDT_BSC_CONTRACT, "blockNumber": "0xf0", "value": "0x0"}
    receipt = evm_token_receipt([usdt_bsc_log(DEPOSIT_EVM, 100 * 10**18)], status="0x0")
    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=evm_fetch(tx=tx, receipt=receipt)))
    assert result.status == chainverify.STATUS_FAILED
    assert "reverted" in result.detail


def test_evm_wrong_contract_fails():
    tx = {"hash": EVM_HASH, "to": "0x9999999999999999999999999999999999999999", "blockNumber": "0xf0", "value": "0x0"}
    receipt = evm_token_receipt([usdt_bsc_log(DEPOSIT_EVM, 100 * 10**18)])
    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=evm_fetch(tx=tx, receipt=receipt)))
    assert result.status == chainverify.STATUS_FAILED


def test_evm_not_found_is_pending():
    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=evm_fetch(tx=None, receipt=None)))
    assert result.status == chainverify.STATUS_PENDING


def test_evm_needs_more_confirmations_is_pending():
    tx = {"hash": EVM_HASH, "to": USDT_BSC_CONTRACT, "blockNumber": "0xf0", "value": "0x0"}
    receipt = evm_token_receipt([usdt_bsc_log(DEPOSIT_EVM, 100 * 10**18)])
    fetch = evm_fetch(tx=tx, receipt=receipt, tip="0xf2")  # only 3 confirmations
    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=fetch))
    assert result.status == chainverify.STATUS_PENDING
    assert result.confirmations == 3


def test_evm_native_eth_verified_without_amount_check():
    tx = {"hash": EVM_HASH, "to": DEPOSIT_EVM, "blockNumber": "0xf0", "value": hex(2 * 10**17)}
    receipt = evm_token_receipt([])
    result = run(chainverify.verify_payment(settings(), "ETH", "ERC20", DEPOSIT_EVM, Decimal("99999"), EVM_HASH, fetch=evm_fetch(tx=tx, receipt=receipt)))
    assert result.status == chainverify.STATUS_VERIFIED
    assert result.amount == Decimal("0.2")
    assert "not USD-pegged" in result.detail


def test_evm_falls_back_to_rpc_when_etherscan_plan_lacks_chain():
    """Free Etherscan plans reject some chains (e.g. BSC) — public RPC must take over."""
    tx = {"hash": EVM_HASH, "to": USDT_BSC_CONTRACT, "blockNumber": "0xf0", "value": "0x0"}
    receipt = evm_token_receipt([usdt_bsc_log(DEPOSIT_EVM, 100 * 10**18)])

    async def fetch(url, params, headers, json_body=None):
        if json_body is None:  # Etherscan-style GET: plan does not include this chain
            return {"status": "0", "message": "Free API access is not supported for this chain."}
        method = json_body["method"]
        if method == "eth_getTransactionByHash":
            return {"jsonrpc": "2.0", "id": 1, "result": tx}
        if method == "eth_getTransactionReceipt":
            return {"jsonrpc": "2.0", "id": 1, "result": receipt}
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": "0x104"}
        raise AssertionError(f"unexpected RPC method: {method}")

    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=fetch))
    assert result.status == chainverify.STATUS_VERIFIED
    assert result.amount == Decimal("100")


def test_evm_all_providers_down_is_pending():
    async def fetch(url, params, headers, json_body=None):
        if json_body is None:
            return {"status": "0", "message": "NOTOK"}
        raise OSError("connection refused")

    result = run(chainverify.verify_payment(settings(), "USDT", "BEP20", DEPOSIT_EVM, Decimal("100"), EVM_HASH, fetch=fetch))
    assert result.status == chainverify.STATUS_PENDING


# ---------------------------------------------------------------- TRON

def tron_fetch(rows):
    async def fetch(url, params, headers, json_body=None):
        assert "transactions/trc20" in url
        assert params.get("contract_address") == USDT_TRON_CONTRACT
        assert params.get("only_confirmed") == "true"
        return {"success": True, "data": rows}

    return fetch


def trc20_row(to_address=DEPOSIT_TRON, value="250000000", contract=USDT_TRON_CONTRACT, tx_id=TRON_HASH):
    return {"transaction_id": tx_id, "to": to_address, "value": value, "token_info": {"address": contract, "decimals": 6}}


def test_tron_usdt_verified():
    result = run(chainverify.verify_payment(settings(), "USDT", "TRC20", DEPOSIT_TRON, Decimal("100"), TRON_HASH, fetch=tron_fetch([trc20_row()])))
    assert result.status == chainverify.STATUS_VERIFIED
    assert result.amount == Decimal("250")
    assert "tronscan.org" in (result.explorer_url or "")


def test_tron_not_confirmed_is_pending():
    result = run(chainverify.verify_payment(settings(), "USDT", "TRC20", DEPOSIT_TRON, Decimal("100"), TRON_HASH, fetch=tron_fetch([])))
    assert result.status == chainverify.STATUS_PENDING


def test_tron_wrong_recipient_fails():
    result = run(chainverify.verify_payment(settings(), "USDT", "TRC20", DEPOSIT_TRON, Decimal("100"), TRON_HASH, fetch=tron_fetch([trc20_row(to_address="TSomeOtherAddress1111111111111111111")])))
    assert result.status == chainverify.STATUS_FAILED
    assert "different address" in result.detail


def test_tron_amount_too_low_fails():
    result = run(chainverify.verify_payment(settings(), "USDT", "TRC20", DEPOSIT_TRON, Decimal("100"), TRON_HASH, fetch=tron_fetch([trc20_row(value="50000000")])))
    assert result.status == chainverify.STATUS_FAILED


# ---------------------------------------------------------------- BITCOIN

def btc_fetch(tx_payload, tip_height=800010):
    async def fetch(url, params, headers, json_body=None):
        if url.endswith("/blocks/tip/height"):
            return {"result": tip_height}
        return tx_payload

    return fetch


def btc_tx(confirmed=True, block_height=800000, vout=None):
    return {
        "txid": BTC_HASH,
        "status": {"confirmed": confirmed, "block_height": block_height if confirmed else None},
        "vout": vout if vout is not None else [{"scriptpubkey_address": DEPOSIT_BTC, "value": 500000}],
    }


def test_btc_verified():
    result = run(chainverify.verify_payment(settings(), "BTC", "BTC", DEPOSIT_BTC, Decimal("100"), BTC_HASH, fetch=btc_fetch(btc_tx())))
    assert result.status == chainverify.STATUS_VERIFIED
    assert result.amount == Decimal("0.005")
    assert result.confirmations == 11


def test_btc_unconfirmed_is_pending():
    result = run(chainverify.verify_payment(settings(), "BTC", "BTC", DEPOSIT_BTC, Decimal("100"), BTC_HASH, fetch=btc_fetch(btc_tx(confirmed=False))))
    assert result.status == chainverify.STATUS_PENDING


def test_btc_no_payment_to_address_fails():
    vout = [{"scriptpubkey_address": "bc1qsomeoneelse000000000000000000000000000", "value": 500000}]
    result = run(chainverify.verify_payment(settings(), "BTC", "BTC", DEPOSIT_BTC, Decimal("100"), BTC_HASH, fetch=btc_fetch(btc_tx(vout=vout))))
    assert result.status == chainverify.STATUS_FAILED


def test_btc_unknown_tx_is_pending():
    result = run(chainverify.verify_payment(settings(), "BTC", "BTC", DEPOSIT_BTC, Decimal("100"), BTC_HASH, fetch=btc_fetch({"_http_status": 404})))
    assert result.status == chainverify.STATUS_PENDING


# ---------------------------------------------------------------- migrations

def test_ensure_transaction_columns_sqlite():
    from sqlalchemy.ext.asyncio import create_async_engine

    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE TABLE transactions (tx_id INTEGER PRIMARY KEY, status VARCHAR(16))")
            await conn.run_sync(_ensure_transaction_columns_sync)
            rows = await conn.exec_driver_sql("PRAGMA table_info('transactions')")
            columns = {row[1] for row in rows.fetchall()}
        await engine.dispose()
        return columns

    columns = run(main())
    assert {"chain_tx_hash", "verify_status", "verified_amount", "verify_detail"} <= columns
