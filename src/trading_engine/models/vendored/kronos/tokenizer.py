"""Financial time-series tokenizer discretizing normalized price returns into vocabulary tokens."""

from __future__ import annotations

import math
from typing import Sequence


class KronosTokenizer:
    """Discretizes continuous financial returns into discrete token IDs.

    Uses logarithmic returns mapped into uniform vocabulary bins centered around zero:
    r_t = ln(P_t / P_{t-1})
    """

    def __init__(
        self,
        vocab_size: int = 1024,
        max_return: float = 0.15,  # +/- 15% maximum return clip
        pad_token_id: int = 0,
        eos_token_id: int = 1,
    ) -> None:
        if vocab_size < 16 or vocab_size % 2 != 0:
            raise ValueError(f"vocab_size must be an even integer >= 16, got {vocab_size}")
        if max_return <= 0.0:
            raise ValueError(f"max_return must be positive, got {max_return}")

        self.vocab_size = vocab_size
        self.max_return = max_return
        self.pad_token_id = pad_token_id
        self.eos_token_id = eos_token_id

        # Reserve first 4 tokens for special tokens [PAD, EOS, BOS, UNK]
        self.num_special_tokens = 4
        self.num_return_bins = vocab_size - self.num_special_tokens
        self.half_bins = self.num_return_bins / 2.0
        self.bin_width = (2.0 * max_return) / self.num_return_bins

    def encode_returns(self, returns: Sequence[float]) -> list[int]:
        """Convert a sequence of fractional or log returns into discrete token IDs."""
        tokens: list[int] = []
        for r in returns:
            # Clip return to [-max_return, max_return]
            clipped = max(-self.max_return, min(self.max_return, float(r)))
            # Map [-max_return, max_return] -> [0, num_return_bins - 1]
            bin_idx = int((clipped + self.max_return) / self.bin_width)
            bin_idx = max(0, min(self.num_return_bins - 1, bin_idx))
            token_id = self.num_special_tokens + bin_idx
            tokens.append(token_id)
        return tokens

    def decode_returns(self, tokens: Sequence[int]) -> list[float]:
        """Convert token IDs back into expected returns (bin centers)."""
        returns: list[float] = []
        for tok in tokens:
            if tok < self.num_special_tokens:
                # Special tokens correspond to neutral zero return
                returns.append(0.0)
                continue
            bin_idx = tok - self.num_special_tokens
            # Bin center
            ret = -self.max_return + (bin_idx + 0.5) * self.bin_width
            returns.append(ret)
        return returns

    def prices_to_tokens(self, prices: Sequence[float]) -> list[int]:
        """Convert a raw price series into return tokens."""
        if len(prices) < 2:
            return []
        log_returns = [
            math.log(max(1e-8, prices[i]) / max(1e-8, prices[i - 1]))
            for i in range(1, len(prices))
        ]
        return self.encode_returns(log_returns)

    def tokens_to_prices(self, base_price: float, tokens: Sequence[int]) -> list[float]:
        """Reconstruct future price trajectory from starting base price and return tokens."""
        returns = self.decode_returns(tokens)
        future_prices: list[float] = []
        current = base_price
        for r in returns:
            current = max(0.01, current * math.exp(r))
            future_prices.append(round(current, 4))
        return future_prices
