// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * CASRSv2 — on-chain implementation of core risk metrics (P_safe, A, K, STS).
 * State is updated by the owner/bot via updateReserves + updateSystemState.
 * Ring buffer of 24 spot prices provides a simple TWAP analogue.
 */
contract CASRSv2 {
    // --- ERC20 ---
    string public constant name = "CAS Reserve Stable v2";
    string public constant symbol = "CASRSv2";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    // --- Roles ---
    address public owner;
    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    // --- Params (configurable) ---
    struct Params {
        uint256 hRS;        // 1e18 scale (e.g. 0.50e18)
        uint256 hRG;        // 1e18
        uint256 rho;        // 1e18 stress fraction
        uint256 omega;      // 1e18 unwind fraction
        uint256 minCoverage; // 1e18 threshold for K
        uint256 fee;        // swap fee 1e18 (e.g. 0.003e18)
    }
    Params public params;

    // --- System state (owner-updated) ---
    struct State {
        uint256 B;   // base assets (MATIC equivalent) 1e18
        uint256 C;   // collateral CASRS 1e18
        uint256 R_RS;// reserves CASRS 1e18
        uint256 R_RG;// reserves CASRG 1e18
        uint256 F;   // free float (tokens) 1e18
        uint256 D;   // debt (CASRG total) 1e18
        uint256 S;   // supply CASRS 1e18
        uint256 X;   // AMM base reserve
        uint256 Y;   // AMM quote reserve
    }
    State public state;

    // --- TWAP ring buffer ---
    uint256[24] public prices;
    uint8 public priceCount;
    uint8 public priceIndex;

    // --- Metrics ---
    struct Metrics {
        uint256 P_spot;
        uint256 P_twap;
        uint256 P_safe;
        uint256 A;
        uint256 K;
        uint256 STS;
        bool emergency;
        bool emissionPaused;
    }
    Metrics public metrics;

    event MetricsUpdated(Metrics m);
    event ParamsUpdated(Params p);
    event StateUpdated(State s);
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(
        uint256 _initialPrice // 1e18
    ) {
        owner = msg.sender;
        params = Params({
            hRS: 50e16,
            hRG: 90e16,
            rho: 10e16,
            omega: 5e16,
            minCoverage: 120e16,
            fee: 3e15
        });
        // mint initial supply to owner
        _mint(msg.sender, 1_000_000 ether);
        // seed price history
        prices[0] = _initialPrice;
        priceCount = 1;
        priceIndex = 1;
        metrics.P_spot = _initialPrice;
        metrics.P_twap = _initialPrice;
        metrics.P_safe = _initialPrice;
    }

    // --- ERC20 core ---
    function _mint(address to, uint256 amount) internal {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function _burn(address from, uint256 amount) internal {
        require(balanceOf[from] >= amount, "insufficient");
        balanceOf[from] -= amount;
        totalSupply -= amount;
        emit Transfer(from, address(0), amount);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= amount, "allowance");
        if (allowed != type(uint256).max) allowance[from][msg.sender] = allowed - amount;
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(balanceOf[from] >= amount, "balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }

    // --- Owner updates ---
    function setParams(
        uint256 hRS,
        uint256 hRG,
        uint256 rho,
        uint256 omega,
        uint256 minCoverage,
        uint256 fee
    ) external onlyOwner {
        params = Params(hRS, hRG, rho, omega, minCoverage, fee);
        emit ParamsUpdated(params);
    }

    function updateReserves(uint256 X, uint256 Y, uint256 F) external onlyOwner {
        state.X = X;
        state.Y = Y;
        state.F = F;
        _updatePrices();
        _recalc();
        emit StateUpdated(state);
    }

    function updateSystemState(
        uint256 B,
        uint256 C,
        uint256 R_RS,
        uint256 R_RG,
        uint256 D,
        uint256 S
    ) external onlyOwner {
        state.B = B;
        state.C = C;
        state.R_RS = R_RS;
        state.R_RG = R_RG;
        state.D = D;
        state.S = S;
        _recalc();
        emit StateUpdated(state);
    }

    // --- Price helpers ---
    function _updatePrices() internal {
        uint256 P_spot = (state.X == 0) ? metrics.P_spot : (state.Y * 1e18) / state.X;
        metrics.P_spot = P_spot;
        // ring buffer TWAP 24 samples
        prices[priceIndex] = P_spot;
        if (priceCount < 24) priceCount++;
        priceIndex = (priceIndex + 1) % 24;

        uint256 sum = 0;
        for (uint8 i = 0; i < priceCount; i++) sum += prices[i];
        metrics.P_twap = sum / priceCount;
    }

    // --- Math model on-chain ---
    function _liquidationValue(uint256 X, uint256 Y, uint256 x) internal view returns (uint256) {
        if (x == 0) return 0;
        uint256 denominator = X + (x * (1e18 - params.fee)) / 1e18;
        if (denominator == 0) return 0;
        // all in 1e18 scale for price: Y/X ~ price
        // We use raw units; consistent with model since price = Y/X
        return (Y * 1e18) - (X * Y * 1e18) / denominator;
    }

    function _exitPrice(uint256 X, uint256 Y, uint256 x) internal view returns (uint256) {
        if (x == 0) return (X > 0) ? (Y * 1e18) / X : 0;
        uint256 lv = _liquidationValue(X, Y, x);
        return lv / x;
    }

    function _recalc() internal {
        uint256 P_spot = metrics.P_spot;
        uint256 P_twap = metrics.P_twap;
        uint256 F = state.F;
        uint256 x_stress = (params.rho * F) / 1e18;
        uint256 P_exit = _exitPrice(state.X, state.Y, x_stress);
        uint256 P_safe = P_twap < P_exit ? P_twap : P_exit;

        uint256 collateral = ((1e18 - params.hRS) * state.C / 1e18) * P_safe / 1e18;
        uint256 reserve = ((1e18 - params.hRS) * state.R_RS / 1e18) * P_safe / 1e18;
        uint256 rg = (params.hRG * state.R_RG) / 1e18;
        uint256 A = state.B + collateral + reserve + rg;

        uint256 unwind = (params.omega * state.D) / 1e18;
        uint256 K = state.D > 0 ? (A > unwind ? (A - unwind) * 1e18 / state.D : 0) : type(uint256).max;

        uint256 lv_stress = _liquidationValue(state.X, state.Y, x_stress);
        uint256 numerator = state.B + lv_stress + ((1e18 - params.hRS) * state.C / 1e18) * P_safe / 1e18 + (params.hRG * state.R_RG) / 1e18;
        uint256 denominator = state.D + unwind;
        uint256 STS = denominator > 0 ? numerator * 1e18 / denominator : type(uint256).max;

        bool emergency = STS < 1e18;
        bool paused = K < params.minCoverage;

        metrics = Metrics({
            P_spot: P_spot,
            P_twap: P_twap,
            P_safe: P_safe,
            A: A,
            K: K,
            STS: STS,
            emergency: emergency,
            emissionPaused: paused
        });

        emit MetricsUpdated(metrics);
    }

    // --- Views ---
    function getMetrics() external view returns (Metrics memory) {
        return metrics;
    }
}
