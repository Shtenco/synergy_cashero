// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface ICASRSv2 {
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
    function balanceOf(address) external view returns (uint256);
    function transferFrom(address,address,uint256) external returns (bool);
    function transfer(address,uint256) external returns (bool);
    function allowance(address,address) external view returns (uint256);
    function approve(address,uint256) external returns (bool);
    function totalSupply() external view returns (uint256);
    function getMetrics() external view returns (Metrics memory);
    function params() external view returns (uint256 hRS,uint256 hRG,uint256 rho,uint256 omega,uint256 minCoverage,uint256 fee);
}

/**
 * CASRGv2 — debt token tightly coupled with CASRSv2 metrics.
 * Minting/repay respect K/minCoverage and emissionPaused.
 */
contract CASRGv2 {
    string public constant name = "CAS Regulator v2";
    string public constant symbol = "CASRGv2";
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    address public owner;
    ICASRSv2 public casrs;
    uint256 public totalCollateral;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event Minted(address indexed user, uint256 rsIn, uint256 rgOut);
    event Repaid(address indexed user, uint256 rgBurn, uint256 rsOut);
    event Liquidated(address indexed user, address indexed keeper, uint256 collateralSeized);

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    constructor(address casrsAddress) {
        owner = msg.sender;
        casrs = ICASRSv2(casrsAddress);
    }

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

    function mintAgainstCollateral(uint256 rsAmount) external {
        require(rsAmount > 0, "amount 0");
        ICASRSv2.Metrics memory m = casrs.getMetrics();
        require(!m.emissionPaused, "emission paused");
        // require coverage K >= minCoverage
        (, , , , uint256 minCov,) = casrs.params();
        require(m.K >= minCov, "coverage low");

        // pull RS
        require(casrs.allowance(msg.sender, address(this)) >= rsAmount, "allowance rs");
        casrs.transferFrom(msg.sender, address(this), rsAmount);
        totalCollateral += rsAmount;

        // mint RG at 50% LTV of P_safe
        uint256 P_safe = m.P_safe; // 1e18
        uint256 rgOut = (rsAmount * P_safe) / (2 * 1e18);
        _mint(msg.sender, rgOut);
        emit Minted(msg.sender, rsAmount, rgOut);
    }

    function repay(uint256 rgAmount) external {
        require(rgAmount > 0, "amount 0");
        _burn(msg.sender, rgAmount);

        uint256 P_safe = casrs.getMetrics().P_safe;
        uint256 rsRelease = (rgAmount * 2 * 1e18) / P_safe;
        if (rsRelease > totalCollateral) rsRelease = totalCollateral;

        totalCollateral -= rsRelease;
        casrs.transfer(msg.sender, rsRelease);
        emit Repaid(msg.sender, rgAmount, rsRelease);
    }

    function liquidate(address user) external {
        uint256 debt = balanceOf[user];
        require(debt > 0, "no debt");
        uint256 coll = totalCollateral; // global; simplified — keeper seizes proportional
        ICASRSv2.Metrics memory m = casrs.getMetrics();
        (,, , , uint256 minCov, ) = casrs.params();
        require(m.K < minCov, "healthy");

        _burn(user, debt);
        // seize share proportional to debt / totalSupply_before
        uint256 seize = coll * debt / (totalSupply + debt);
        totalCollateral -= seize;
        casrs.transfer(msg.sender, seize);
        emit Liquidated(user, msg.sender, seize);
    }
}
