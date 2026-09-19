"""On-chain deposit verification for SAFE SELL and wallet top-up flows.

Verifies that a user-submitted transaction hash really paid the bot's
deposit address before an admin is allowed to credit anything:

- EVM chains (Ethereum / BSC / Polygon / Base / Arbitrum / Optimism), trying
  in order: Etherscan V2 multichain API -> Infura JSON-RPC -> public RPC
  endpoints. Public RPCs need no key, so verification still works when a
  free Etherscan plan does not include a chain (e.g. BSC).
- TRON (TRC-20) via TronGrid (key optional).
- Bitcoin via the free blockstream.info REST API (no key needed).

Only USD-pegged tokens (USDT/USDC) are amount-checked against the expected
USD figure. For volatile assets the verifier confirms chain, recipient,
asset and confirmations, and reports the raw on-chain amount so the admin
can see exactly what arrived.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Mapping

import aiohttp

from .config import Settings

STATUS_VERIFIED = "verified"
STATUS_PENDING = "pending"
STATUS_FAILED = "failed"
STATUS_UNSUPPORTED = "unsupported"

STABLE_TOLERANCE = Decimal("0.99")  # accept >= 99% of the expected USD value
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

ETHERSCAN_BASE = "https://api.etherscan.io/v2/api"
TRONGRID_BASE = "https://api.trongrid.io"
BLOCKSTREAM_BASE = "https://blockstream.info/api"

# Chain label (as used in bot keyboards) -> EVM chain id.
EVM_CHAIN_IDS: dict[str, int] = {
    "ERC20": 1,
    "ETHEREUM": 1,
    "BEP20": 56,
    "BSC": 56,
    "MATIC": 137,
    "POLYGON": 137,
    "BASE": 8453,
    "ARBITRUM": 42161,
    "OPTIMISM": 10,
}

TRON_CHAINS = {"TRC20", "TRON"}
BTC_CHAINS = {"BTC", "BITCOIN"}

DEFAULT_CONFIRMATIONS: dict[int, int] = {
    1: 12,
    56: 15,
    137: 32,
    8453: 12,
    42161: 12,
    10: 12,
}

EVM_EXPLORERS: dict[int, str] = {
    1: "https://etherscan.io",
    56: "https://bscscan.com",
    137: "https://polygonscan.com",
    8453: "https://basescan.org",
    42161: "https://arbiscan.io",
    10: "https://optimistic.etherscan.io",
}

# Infura JSON-RPC hosts per chain (BSC is not offered by Infura).
INFURA_HOSTS: dict[int, str] = {
    1: "mainnet",
    137: "polygon-mainnet",
    42161: "arbitrum-mainnet",
    10: "optimism-mainnet",
    8453: "base-mainnet",
}

# Free public JSON-RPC endpoints, used as fallback with no key required.
PUBLIC_RPC: dict[int, list[str]] = {
    1: ["https://eth.llamarpc.com", "https://cloudflare-eth.com"],
    56: ["https://bsc-dataseed.binance.org", "https://bsc-dataseed1.defibit.io", "https://rpc.ankr.com/bsc"],
    137: ["https://polygon-rpc.com", "https://rpc.ankr.com/polygon"],
    8453: ["https://mainnet.base.org", "https://rpc.ankr.com/base"],
    42161: ["https://arb1.arbitrum.io/rpc", "https://rpc.ankr.com/arbitrum"],
    10: ["https://mainnet.optimism.io", "https://rpc.ankr.com/optimism"],
}

# (chain id, token) -> (contract address, decimals, is_usd_pegged).
# None contract means the chain's native asset.
EVM_TOKENS: dict[tuple[int, str], tuple[str | None, int, bool]] = {
    (1, "USDT"): ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6, True),
    (1, "USDC"): ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6, True),
    (1, "ETH"): (None, 18, False),
    (56, "USDT"): ("0x55d398326f99059fF775485246999027B3197955", 18, True),
    (56, "USDC"): ("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", 18, True),
    (56, "ETH"): ("0x2170Ed0880ac9A755fd29B2688956BD959F933F8", 18, False),  # Binance-Peg ETH
    (56, "BNB"): (None, 18, False),
    (56, "BTC"): ("0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c", 18, False),  # BTCB
    (137, "USDT"): ("0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6, True),
    (137, "USDC"): ("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6, True),
    (137, "ETH"): ("0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619", 18, False),
    (8453, "USDC"): ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6, True),
    (8453, "ETH"): (None, 18, False),
    (42161, "USDT"): ("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6, True),
    (42161, "ETH"): (None, 18, False),
    (10, "USDT"): ("0x94b008aA00579c1307B0EF2c499aD98a8ce58e58", 6, True),
    (10, "ETH"): (None, 18, False),
}

# token -> (contract id, decimals, is_usd_pegged) on TRON.
TRON_TOKENS: dict[str, tuple[str, int, bool]] = {
    "USDT": ("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", 6, True),
}

HEX64 = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")

# (url, query params, headers, json body) -> decoded JSON payload
Fetch = Callable[
    [str, Mapping[str, Any] | None, Mapping[str, str] | None, Mapping[str, Any] | None],
    Awaitable[dict[str, Any]],
]


@dataclass(frozen=True)
class VerificationResult:
    status: str  # STATUS_VERIFIED / STATUS_PENDING / STATUS_FAILED / STATUS_UNSUPPORTED
    detail: str = ""
    amount: Decimal | None = None  # on-chain amount in token units
    confirmations: int | None = None
    explorer_url: str | None = None


@dataclass(frozen=True)
class EvmProvider:
    kind: str  # "etherscan" (GET, query params) or "rpc" (JSON-RPC POST)
    url: str


class ProvidersUnavailable(Exception):
    """Every configured provider errored out — the caller should retry later."""


def _clean_hex(value: str) -> str:
    return value.strip().lower()


def _same_address(a: str, b: str) -> bool:
    return a.strip().lower().removeprefix("0x") == b.strip().lower().removeprefix("0x")


def normalize_tx_hash(raw: str, chain: str) -> str | None:
    """Return a canonical hash for the chain, or None if the input is not a hash."""
    value = raw.strip()
    if not HEX64.match(value):
        return None
    label = chain.strip().upper()
    if label in EVM_CHAIN_IDS:
        body = value.removeprefix("0x").removeprefix("0X")
        return "0x" + body.lower()
    # TRON / Bitcoin hashes are plain hex without 0x.
    return value.removeprefix("0x").removeprefix("0X").lower()


def chain_family(chain: str) -> str | None:
    label = chain.strip().upper()
    if label in TRON_CHAINS:
        return "tron"
    if label in BTC_CHAINS:
        return "btc"
    if label in EVM_CHAIN_IDS:
        return "evm"
    return None


def explorer_url(chain: str, tx_hash: str) -> str | None:
    label = chain.strip().upper()
    if label in TRON_CHAINS:
        return f"https://tronscan.org/#/transaction/{tx_hash}"
    if label in BTC_CHAINS:
        return f"https://mempool.space/tx/{tx_hash}"
    chain_id = EVM_CHAIN_IDS.get(label)
    if chain_id is None:
        return None
    host = EVM_EXPLORERS.get(chain_id)
    return f"{host}/tx/{tx_hash}" if host else None


def support_status(settings: Settings, token: str | None, chain: str | None, address: str | None) -> tuple[bool, str]:
    """Whether (token, chain, address) can be verified on-chain automatically."""
    del settings  # kept in the signature for future key requirements
    if not token or not chain or not address:
        return False, "incomplete payment details"
    if address.startswith("CONFIGURE_"):
        return False, "deposit address is not configured"
    family = chain_family(chain)
    token_label = token.strip().upper()
    if family == "evm":
        chain_id = EVM_CHAIN_IDS[chain.strip().upper()]
        if (chain_id, token_label) not in EVM_TOKENS:
            return False, f"no trusted {token_label} registry entry on this EVM chain"
        return True, ""
    if family == "tron":
        if token_label not in TRON_TOKENS:
            return False, f"no trusted {token_label} registry entry on TRON"
        return True, ""
    if family == "btc":
        if token_label != "BTC":
            return False, "only native BTC can be verified on the Bitcoin chain"
        return True, ""
    return False, f"unsupported network: {chain}"


async def _make_fetcher() -> tuple[aiohttp.ClientSession, Fetch]:
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))

    async def fetch(url, params=None, headers=None, json_body=None):
        if json_body is not None:
            async with session.post(url, json=json_body, headers=dict(headers or {})) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        async with session.get(url, params=dict(params or {}), headers=dict(headers or {})) as response:
            if response.status == 404:
                return {"_http_status": 404}
            response.raise_for_status()
            return await response.json(content_type=None)

    return session, fetch


async def verify_payment(
    settings: Settings,
    token: str,
    chain: str,
    deposit_address: str,
    expected_usd: Decimal,
    tx_hash: str,
    *,
    fetch: Fetch | None = None,
) -> VerificationResult:
    """Verify a single payment. Retries are the caller's responsibility."""
    supported, reason = support_status(settings, token, chain, deposit_address)
    if not supported:
        return VerificationResult(status=STATUS_UNSUPPORTED, detail=reason)
    if fetch is None:
        session, fetcher = await _make_fetcher()
        try:
            return await _verify(settings, token, chain, deposit_address, expected_usd, tx_hash, fetcher)
        finally:
            await session.close()
    return await _verify(settings, token, chain, deposit_address, expected_usd, tx_hash, fetch)


async def _verify(settings, token, chain, deposit_address, expected_usd, tx_hash, fetch) -> VerificationResult:
    family = chain_family(chain)
    try:
        if family == "evm":
            return await _verify_evm(settings, token, chain, deposit_address, expected_usd, tx_hash, fetch)
        if family == "tron":
            return await _verify_tron(settings, token, deposit_address, expected_usd, tx_hash, fetch)
        if family == "btc":
            return await _verify_btc(deposit_address, tx_hash, fetch)
    except ProvidersUnavailable as exc:
        return VerificationResult(status=STATUS_PENDING, detail=f"verification services unavailable: {exc}")
    except (aiohttp.ClientError, ValueError, KeyError, TypeError, OSError, asyncio.TimeoutError) as exc:
        return VerificationResult(status=STATUS_PENDING, detail=f"verification service error: {exc}")
    return VerificationResult(status=STATUS_UNSUPPORTED, detail=f"unsupported network: {chain}")


# --------------------------------------------------------------------------- EVM

def _infura_key(settings: Settings) -> str | None:
    if settings.infura_api_key:
        return settings.infura_api_key
    if settings.infura_url:
        tail = settings.infura_url.rstrip("/").rsplit("/", 1)[-1]
        return tail or None
    return None


def _evm_providers(settings: Settings, chain_id: int) -> list[EvmProvider]:
    providers: list[EvmProvider] = []
    if settings.etherscan_api_key:
        providers.append(EvmProvider("etherscan", ETHERSCAN_BASE))
    infura_key = _infura_key(settings)
    infura_host = INFURA_HOSTS.get(chain_id)
    if infura_key and infura_host:
        providers.append(EvmProvider("rpc", f"https://{infura_host}.infura.io/v3/{infura_key}"))
    providers.extend(EvmProvider("rpc", url) for url in PUBLIC_RPC.get(chain_id, []))
    return providers


async def _evm_call(settings, fetch, chain_id, action, rpc_method, rpc_params, extra_query=None):
    """Try each provider in order; return the first usable `result` (may be None)."""
    for provider in _evm_providers(settings, chain_id):
        try:
            if provider.kind == "etherscan":
                params = {
                    "chainid": chain_id,
                    "module": "proxy",
                    "action": action,
                    "apikey": settings.etherscan_api_key,
                }
                params.update(extra_query or {})
                payload = await fetch(provider.url, params, None, None)
            else:
                payload = await fetch(
                    provider.url,
                    None,
                    None,
                    {"jsonrpc": "2.0", "id": 1, "method": rpc_method, "params": rpc_params},
                )
        except (aiohttp.ClientError, OSError, ValueError, asyncio.TimeoutError):
            continue
        # A usable answer has a "result" key (None = legitimately not found).
        # Rejections like Etherscan plan limits carry only "message"/"error".
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
    raise ProvidersUnavailable(f"chain {chain_id}")


async def _verify_evm(settings, token, chain, deposit_address, expected_usd, tx_hash, fetch) -> VerificationResult:
    chain_id = EVM_CHAIN_IDS[chain.strip().upper()]
    contract, decimals, is_stable = EVM_TOKENS[(chain_id, token.strip().upper())]
    min_confirmations = _min_confirmations(settings, chain_id)

    tx = await _evm_call(settings, fetch, chain_id, "eth_getTransactionByHash", "eth_getTransactionByHash", [tx_hash], {"txhash": tx_hash})
    if not isinstance(tx, dict) or not tx.get("hash"):
        return VerificationResult(status=STATUS_PENDING, detail="transaction not found yet (still propagating)")

    receipt = await _evm_call(settings, fetch, chain_id, "eth_getTransactionReceipt", "eth_getTransactionReceipt", [tx_hash], {"txhash": tx_hash})
    if not isinstance(receipt, dict):
        return VerificationResult(status=STATUS_PENDING, detail="transaction is not mined yet")

    if _clean_hex(receipt.get("status", "0x0")) != "0x1":
        return VerificationResult(status=STATUS_FAILED, detail="transaction reverted on-chain")

    block_hex = tx.get("blockNumber") or receipt.get("blockNumber")
    if not block_hex:
        return VerificationResult(status=STATUS_PENDING, detail="waiting for the transaction to be mined")
    tip_hex = await _evm_call(settings, fetch, chain_id, "eth_blockNumber", "eth_blockNumber", [])
    if not tip_hex:
        return VerificationResult(status=STATUS_PENDING, detail="could not read the latest block height")
    confirmations = int(tip_hex, 16) - int(block_hex, 16) + 1
    if confirmations < min_confirmations:
        return VerificationResult(
            status=STATUS_PENDING,
            detail=f"confirming: {confirmations}/{min_confirmations} blocks",
            confirmations=confirmations,
        )

    if contract is None:
        amount = _verify_native_evm(tx, deposit_address, decimals)
    else:
        amount = _verify_token_evm(tx, receipt, contract, deposit_address, decimals)

    url = explorer_url(chain, tx_hash)
    if amount is None:
        return VerificationResult(status=STATUS_FAILED, detail=f"no {token} transfer to the deposit address in this transaction", confirmations=confirmations, explorer_url=url)

    if amount <= 0:
        return VerificationResult(status=STATUS_FAILED, detail="the transferred amount is zero", confirmations=confirmations, explorer_url=url)

    if is_stable and amount < expected_usd * STABLE_TOLERANCE:
        return VerificationResult(
            status=STATUS_FAILED,
            detail=f"received {amount} {token} but at least ${expected_usd:.2f} was expected",
            amount=amount,
            confirmations=confirmations,
            explorer_url=url,
        )

    detail = f"{amount} {token} received on {chain}"
    if not is_stable:
        detail += " (amount is not USD-pegged — check value at current rate)"
    return VerificationResult(status=STATUS_VERIFIED, detail=detail, amount=amount, confirmations=confirmations, explorer_url=url)


def _verify_native_evm(tx: dict[str, Any], deposit_address: str, decimals: int) -> Decimal | None:
    if not _same_address(tx.get("to") or "", deposit_address):
        return None
    try:
        value = int(tx.get("value", "0x0"), 16)
    except (TypeError, ValueError):
        return None
    return Decimal(value) / Decimal(10**decimals)


def _verify_token_evm(tx: dict[str, Any], receipt: dict[str, Any], contract: str, deposit_address: str, decimals: int) -> Decimal | None:
    if not _same_address(tx.get("to") or "", contract):
        return None
    total = 0
    for log in receipt.get("logs") or []:
        if not _same_address(log.get("address") or "", contract):
            continue
        topics = log.get("topics") or []
        if len(topics) != 3 or _clean_hex(topics[0]) != TRANSFER_TOPIC:
            continue
        recipient = topics[2][-40:]  # last 20 bytes of the 32-byte topic
        if recipient.lower() != deposit_address.lower().removeprefix("0x"):
            continue
        try:
            total += int(log.get("data", "0x0"), 16)
        except (TypeError, ValueError):
            continue
    if total <= 0:
        return None
    return Decimal(total) / Decimal(10**decimals)


def _min_confirmations(settings: Settings, chain_id: int) -> int:
    override = getattr(settings, "verify_min_confirmations", None)
    if override:
        return override
    return DEFAULT_CONFIRMATIONS.get(chain_id, 12)


# --------------------------------------------------------------------------- TRON

async def _verify_tron(settings, token, deposit_address, expected_usd, tx_hash, fetch) -> VerificationResult:
    contract, decimals, is_stable = TRON_TOKENS[token.strip().upper()]
    headers = {"TRON-PRO-API-KEY": settings.trongrid_api_key} if settings.trongrid_api_key else None
    url = f"{TRONGRID_BASE}/v1/accounts/{deposit_address}/transactions/trc20"
    params = {"only_confirmed": "true", "only_to": "true", "limit": 200, "contract_address": contract}
    payload = await fetch(url, params, headers, None)
    rows = (payload or {}).get("data") or []

    url_all = explorer_url("TRC20", tx_hash)
    if not rows:
        return VerificationResult(status=STATUS_PENDING, detail="transaction not confirmed yet")

    match = None
    wrong_asset = False
    for row in rows:
        if (row.get("transaction_id") or "").lower() == tx_hash.lower():
            match = row
            info = row.get("token_info") or {}
            if (info.get("address") or "") != contract:
                wrong_asset = True
            break

    if match is None:
        return VerificationResult(status=STATUS_PENDING, detail="transaction not confirmed yet")
    if wrong_asset:
        return VerificationResult(status=STATUS_FAILED, detail="the transaction transfers a different TRON token", explorer_url=url_all)

    info = match.get("token_info") or {}
    decimals = int(info.get("decimals", decimals))
    if (match.get("to") or "") != deposit_address:
        return VerificationResult(status=STATUS_FAILED, detail=f"{token} was sent to a different address", explorer_url=url_all)
    try:
        amount = Decimal(str(match.get("value", "0"))) / Decimal(10**decimals)
    except (InvalidOperation, TypeError):
        return VerificationResult(status=STATUS_FAILED, detail="could not parse the transferred amount", explorer_url=url_all)

    if is_stable and amount < expected_usd * STABLE_TOLERANCE:
        return VerificationResult(
            status=STATUS_FAILED,
            detail=f"received {amount} {token} but at least ${expected_usd:.2f} was expected",
            amount=amount,
            explorer_url=url_all,
        )
    return VerificationResult(status=STATUS_VERIFIED, detail=f"{amount} {token} received on TRC20 (fully confirmed)", amount=amount, explorer_url=url_all)


# --------------------------------------------------------------------------- BITCOIN

async def _verify_btc(deposit_address, tx_hash, fetch) -> VerificationResult:
    url = f"{BLOCKSTREAM_BASE}/tx/{tx_hash}"
    payload = await fetch(url, None, None, None)
    if payload.get("_http_status") == 404 or not payload.get("txid"):
        return VerificationResult(status=STATUS_PENDING, detail="transaction not found on the Bitcoin network yet")

    status = payload.get("status") or {}
    explorer = explorer_url("BTC", tx_hash)
    if not status.get("confirmed"):
        return VerificationResult(status=STATUS_PENDING, detail="transaction is broadcast but not mined yet")

    total_sats = 0
    for out in payload.get("vout") or []:
        if (out.get("scriptpubkey_address") or "") == deposit_address:
            try:
                total_sats += int(out.get("value", 0))
            except (TypeError, ValueError):
                continue
    if total_sats <= 0:
        return VerificationResult(status=STATUS_FAILED, detail="no output pays the deposit address in this transaction", explorer_url=explorer)

    confirmations = 1
    tip_payload = await fetch(f"{BLOCKSTREAM_BASE}/blocks/tip/height", None, None, None)
    try:
        tip_height = int(tip_payload.get("result") or tip_payload.get("height") or 0)
        block_height = int(status.get("block_height") or 0)
        if tip_height and block_height:
            confirmations = max(1, tip_height - block_height + 1)
    except (TypeError, ValueError):
        pass

    amount = Decimal(total_sats) / Decimal(10**8)
    return VerificationResult(
        status=STATUS_VERIFIED,
        detail=f"{amount} BTC received on Bitcoin (amount is not USD-pegged — check value at current rate)",
        amount=amount,
        confirmations=confirmations,
        explorer_url=explorer,
    )
