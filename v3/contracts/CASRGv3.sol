// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface ICASRSv3 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
    function pSafe() external view returns (uint256);
    function hRS() external view returns (uint256);
}

contract CASRGv3 {
    string public constant name = "CAShero Debt v3";
    string public constant symbol = "CASRGv3";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event MintAgainstCollateral(address indexed user, uint256 rsAmount, uint256 rgAmount);
    event Repaid(address indexed user, uint256 rgAmount);
    event Liquidated(address indexed user, uint256 collateralSeized, uint256 debtBurned);

    address public owner;
    address public bot;
    ICASRSv3 public immutable casrs;

    uint256 public collateralFactor = 45e16; // 0.45
    uint256 public mintCR = 22e17; // 2.2
    uint256 public liquidationCR = 14e17; // 1.4

    mapping(address => uint256) public collateralRS;
    mapping(address => uint256) public debtRG;

    modifier onlyOwner() {
        require(msg.sender == owner, "owner only");
        _;
    }

    modifier onlyBotOrOwner() {
        require(msg.sender == owner || msg.sender == bot, "bot/owner only");
        _;
    }

    constructor(address _casrs) {
        owner = msg.sender;
        casrs = ICASRSv3(_casrs);
    }

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

    function setRisk(uint256 _cf, uint256 _mintCR, uint256 _liqCR) external onlyOwner {
        collateralFactor = _cf;
        mintCR = _mintCR;
        liquidationCR = _liqCR;
    }

    function userCR(address user) public view returns (uint256) {
        if (debtRG[user] == 0) return type(uint256).max;
        uint256 pSafe = casrs.pSafe();
        uint256 hRS = casrs.hRS();
        uint256 safeCollateral = ((1e18 - hRS) * collateralRS[user] * pSafe) / 1e36;
        return (safeCollateral * 1e18) / debtRG[user];
    }

    function mintAgainstCollateral(uint256 rsAmount) external {
        require(rsAmount > 0, "zero amount");
        require(casrs.transferFrom(msg.sender, address(this), rsAmount), "collateral transfer failed");

        uint256 pSafe = casrs.pSafe();
        uint256 hRS = casrs.hRS();
        uint256 rgAmount = (collateralFactor * (1e18 - hRS) * rsAmount * pSafe) / 1e54;
        require(rgAmount > 0, "too small");

        collateralRS[msg.sender] += rsAmount;
        debtRG[msg.sender] += rgAmount;
        require(userCR(msg.sender) >= mintCR, "CR too low");

        _mint(msg.sender, rgAmount);
        emit MintAgainstCollateral(msg.sender, rsAmount, rgAmount);
    }

    function repay(uint256 rgAmount) external {
        require(rgAmount > 0, "zero amount");
        if (rgAmount > debtRG[msg.sender]) rgAmount = debtRG[msg.sender];
        _burn(msg.sender, rgAmount);
        debtRG[msg.sender] -= rgAmount;

        // release collateral proportionally
        uint256 release = collateralRS[msg.sender] == 0 ? 0 : (collateralRS[msg.sender] * rgAmount) / (debtRG[msg.sender] + rgAmount);
        if (release > collateralRS[msg.sender]) release = collateralRS[msg.sender];
        collateralRS[msg.sender] -= release;
        require(casrs.transfer(msg.sender, release), "collateral return failed");

        emit Repaid(msg.sender, rgAmount);
    }

    function liquidate(address user) external onlyBotOrOwner {
        require(userCR(user) < liquidationCR, "not liquidatable");
        uint256 debt = debtRG[user];
        uint256 coll = collateralRS[user];
        debtRG[user] = 0;
        collateralRS[user] = 0;

        // bot/owner must burn same debt amount from own balance to close system debt
        if (debt > balanceOf[msg.sender]) debt = balanceOf[msg.sender];
        _burn(msg.sender, debt);
        require(casrs.transfer(msg.sender, coll), "seize failed");
        emit Liquidated(user, coll, debt);
    }
}
