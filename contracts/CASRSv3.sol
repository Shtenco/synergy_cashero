// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IRouterV2 {
    function WETH() external pure returns (address);
    function swapExactETHForTokensSupportingFeeOnTransferTokens(
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external payable;

    function swapExactTokensForETHSupportingFeeOnTransferTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external;

    function addLiquidityETH(
        address token,
        uint amountTokenDesired,
        uint amountTokenMin,
        uint amountETHMin,
        address to,
        uint deadline
    ) external payable returns (uint amountToken, uint amountETH, uint liquidity);
}

contract CASRSv3 {
    string public constant name = "CAShero Savings v3";
    string public constant symbol = "CASRSv3";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    event ParamsUpdated(uint256 hRS, uint256 hRG, uint256 rho, uint256 omega, uint256 minCoverage);
    event StateUpdated(uint256 B, uint256 C, uint256 R_RS, uint256 R_RG, uint256 D, uint256 F, uint256 X, uint256 Y);
    event MintByGrowth(uint256 amount, uint256 toReserve, uint256 toFloat, uint256 toFounder, uint256 toProjects);
    event BurnByDecline(uint256 amount);
    event LiqFundUpdated(uint256 liqFund, uint256 reserveSold, uint256 addedToken, uint256 addedMatic);

    address public owner;
    address public founderVesting;
    address public projectVault;
    address public bot;

    IRouterV2 public immutable router;

    // 1e18 fixed-point params
    uint256 public hRS = 5e17; // 0.5
    uint256 public hRG = 9e17; // 0.9
    uint256 public rho = 1e17; // 0.1
    uint256 public omega = 5e16; // 0.05
    uint256 public minCoverage = 12e17; // 1.2
    uint256 public alpha = 45e16; // 0.45
    uint256 public beta = 35e16; // 0.35

    // additions η,δ,ψ
    uint256 public eta = 5e17; // 0.5 fee share into LP fund
    uint256 public delta = 1e15; // 0.001 reserve sale rate
    uint256 public psi = 2e17; // 0.2 LP deploy share

    uint256 public B;
    uint256 public C;
    uint256 public R_RS;
    uint256 public R_RG;
    uint256 public D;
    uint256 public F;
    uint256 public X;
    uint256 public Y;

    uint256 public pSpot;
    uint256 public pTwap;
    uint256 public pSafe;
    uint256 public lastPriceTs;

    uint256 public liqFundMatic;

    modifier onlyOwner() {
        require(msg.sender == owner, "owner only");
        _;
    }

    modifier onlyBotOrOwner() {
        require(msg.sender == owner || msg.sender == bot, "bot/owner only");
        _;
    }

    constructor(address _router, address _founderVesting, address _projectVault) {
        owner = msg.sender;
        founderVesting = _founderVesting;
        projectVault = _projectVault;
        router = IRouterV2(_router);
    }

    receive() external payable {}

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 a = allowance[from][msg.sender];
        require(a >= amount, "allowance");
        allowance[from][msg.sender] = a - amount;
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(balanceOf[from] >= amount, "balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }

    function _mint(address to, uint256 amount) internal {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function _burn(address from, uint256 amount) internal {
        require(balanceOf[from] >= amount, "balance");
        balanceOf[from] -= amount;
        totalSupply -= amount;
        emit Transfer(from, address(0), amount);
    }

    function setBot(address _bot) external onlyOwner {
        bot = _bot;
    }

    function setParams(
        uint256 _hRS,
        uint256 _hRG,
        uint256 _rho,
        uint256 _omega,
        uint256 _minCoverage,
        uint256 _alpha,
        uint256 _beta,
        uint256 _eta,
        uint256 _delta,
        uint256 _psi
    ) external onlyOwner {
        hRS = _hRS;
        hRG = _hRG;
        rho = _rho;
        omega = _omega;
        minCoverage = _minCoverage;
        alpha = _alpha;
        beta = _beta;
        eta = _eta;
        delta = _delta;
        psi = _psi;
        emit ParamsUpdated(_hRS, _hRG, _rho, _omega, _minCoverage);
    }

    function updateState(
        uint256 _B,
        uint256 _C,
        uint256 _R_RS,
        uint256 _R_RG,
        uint256 _D,
        uint256 _F,
        uint256 _X,
        uint256 _Y,
        uint256 _pTwap
    ) external onlyBotOrOwner {
        B = _B;
        C = _C;
        R_RS = _R_RS;
        R_RG = _R_RG;
        D = _D;
        F = _F;
        X = _X;
        Y = _Y;
        pSpot = _X == 0 ? 0 : (_Y * 1e18) / _X;
        pTwap = _pTwap;
        pSafe = _safePrice();
        lastPriceTs = block.timestamp;
        emit StateUpdated(_B, _C, _R_RS, _R_RG, _D, _F, _X, _Y);
    }

    function _liquidationValue(uint256 x) internal view returns (uint256) {
        if (x == 0 || X == 0 || Y == 0) return 0;
        uint256 eff = (x * (1e18 - 3e15)) / 1e18; // fee 0.3%
        uint256 denom = X + eff;
        if (denom == 0) return 0;
        return Y - ((X * Y) / denom);
    }

    function _safePrice() internal view returns (uint256) {
        if (F == 0) return pTwap;
        uint256 xStress = (rho * F) / 1e18;
        if (xStress == 0) return pTwap;
        uint256 lv = _liquidationValue(xStress);
        uint256 pExit = (lv * 1e18) / xStress;
        return pExit < pTwap ? pExit : pTwap;
    }

    function getSystemAccounting() external view returns (uint256 assetsSafe, uint256 liabilitiesSafe, uint256 equityNav, uint256 coverage) {
        uint256 collateral = ((1e18 - hRS) * C * pSafe) / 1e36;
        uint256 reserveRS = ((1e18 - hRS) * R_RS * pSafe) / 1e36;
        uint256 reserveRG = (hRG * R_RG) / 1e18;
        assetsSafe = B + collateral + reserveRS + reserveRG;
        liabilitiesSafe = D + ((omega * D) / 1e18);
        equityNav = assetsSafe > liabilitiesSafe ? assetsSafe - liabilitiesSafe : 0;
        coverage = D == 0 ? type(uint256).max : ((assetsSafe - ((omega * D) / 1e18)) * 1e18) / D;
    }

    function mintByGrowth(uint256 prevTwap) external onlyBotOrOwner returns (uint256 minted) {
        if (pTwap <= prevTwap || prevTwap == 0) return 0;
        (, , , uint256 coverage) = this.getSystemAccounting();
        require(coverage >= minCoverage, "emission paused");
        uint256 g = ((pTwap - prevTwap) * 1e18) / prevTwap;
        minted = (alpha * totalSupply * g) / 1e36;
        if (minted == 0) return 0;

        uint256 toProjects = (minted * 5) / 100;
        uint256 rem = minted - toProjects;
        uint256 toReserve = (rem * 70) / 100;
        uint256 toFloat = (rem * 20) / 100;
        uint256 toFounder = rem - toReserve - toFloat;

        _mint(projectVault, toProjects);
        _mint(address(this), toReserve);
        _mint(msg.sender, toFloat);
        _mint(founderVesting, toFounder);

        R_RS += toReserve;
        F += toFloat;

        emit MintByGrowth(minted, toReserve, toFloat, toFounder, toProjects);
    }

    function burnByDecline(uint256 prevTwap, uint256 fromTreasuryAmount) external onlyBotOrOwner returns (uint256 burned) {
        if (prevTwap <= pTwap || prevTwap == 0) return 0;
        uint256 d = ((prevTwap - pTwap) * 1e18) / prevTwap;
        burned = (beta * totalSupply * d) / 1e36;
        if (burned > fromTreasuryAmount) burned = fromTreasuryAmount;
        if (burned > balanceOf[address(this)]) burned = balanceOf[address(this)];
        if (burned > 0) {
            _burn(address(this), burned);
            emit BurnByDecline(burned);
        }
    }

    function accrueTradingFee(uint256 volumeMatic, uint256 tau) external onlyBotOrOwner {
        uint256 feeIncome = (volumeMatic * tau) / 1e18;
        uint256 toLiqFund = (feeIncome * eta) / 1e18;
        liqFundMatic += toLiqFund;
        B += (feeIncome - toLiqFund);
    }

    function robotSellReserveAndAddLiquidity(uint256 sellBps, uint256 deployBps, uint256 deadline) external onlyBotOrOwner {
        // sell part of reserve token -> MATIC
        uint256 sellAmount = (R_RS * sellBps) / 10000;
        if (sellAmount > 0) {
            _approveRouter(sellAmount);
            address[] memory path = new address[](2);
            path[0] = address(this);
            path[1] = router.WETH();
            router.swapExactTokensForETHSupportingFeeOnTransferTokens(sellAmount, 0, path, address(this), deadline);
            R_RS -= sellAmount;
        }

        uint256 deployMatic = (liqFundMatic * deployBps) / 10000;
        if (deployMatic > address(this).balance) deployMatic = address(this).balance;
        if (deployMatic > 0) {
            uint256 needToken = pSafe == 0 ? 0 : (deployMatic * 1e18) / pSafe;
            if (needToken > R_RS) needToken = R_RS;
            if (needToken > 0) {
                _approveRouter(needToken);
                router.addLiquidityETH{value: deployMatic}(address(this), needToken, 0, 0, owner, deadline);
                R_RS -= needToken;
                if (liqFundMatic >= deployMatic) liqFundMatic -= deployMatic;
                emit LiqFundUpdated(liqFundMatic, sellAmount, needToken, deployMatic);
            }
        }
    }

    function _approveRouter(uint256 amount) internal {
        allowance[address(this)][address(router)] = amount;
        emit Approval(address(this), address(router), amount);
    }
}
