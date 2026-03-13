require("dotenv").config();
const hre = require("hardhat");

const ROUTER = process.env.ROUTER_V2 || "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const WETH = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";

const ROUTER_ABI = [
  "function swapExactETHForTokensSupportingFeeOnTransferTokens(uint amountOutMin, address[] calldata path, address to, uint deadline) payable",
  "function addLiquidityETH(address token,uint amountTokenDesired,uint amountTokenMin,uint amountETHMin,address to,uint deadline) payable returns (uint amountToken, uint amountETH, uint liquidity)",
];

const ERC20_ABI = [
  "function balanceOf(address) view returns (uint256)",
  "function approve(address spender, uint256 amount) returns (bool)",
];

async function addOneTokenPool(tokenAddr, signer, router) {
  const token = new hre.ethers.Contract(tokenAddr, ERC20_ABI, signer);

  // total 10 POL per pool: 5 POL buy token + 5 POL paired add
  const half = hre.ethers.parseEther("5");

  const before = await token.balanceOf(signer.address);
  const deadline = Math.floor(Date.now() / 1000) + 600;

  const buyTx = await router.swapExactETHForTokensSupportingFeeOnTransferTokens(
    0,
    [WETH, tokenAddr],
    signer.address,
    deadline,
    { value: half }
  );
  await buyTx.wait();

  const after = await token.balanceOf(signer.address);
  const got = after - before;
  if (got <= 0n) {
    console.log("No token acquired for", tokenAddr, "skip pool add");
    return;
  }

  const ap = await token.approve(ROUTER, got);
  await ap.wait();

  const addTx = await router.addLiquidityETH(
    tokenAddr,
    got,
    0,
    0,
    signer.address,
    deadline,
    { value: half }
  );
  await addTx.wait();

  console.log("Added liquidity 10 POL total for token", tokenAddr);
}

async function main() {
  const [signer] = await hre.ethers.getSigners();
  const rs = process.env.CASRSV3_ADDRESS;
  const rg = process.env.CASRGV3_ADDRESS;

  if (!rs || !rg) {
    throw new Error("Set CASRSV3_ADDRESS and CASRGV3_ADDRESS in .env");
  }

  const router = new hre.ethers.Contract(ROUTER, ROUTER_ABI, signer);

  console.log("Signer:", signer.address);
  await addOneTokenPool(rs, signer, router); // +10 POL to CASRS pool
  await addOneTokenPool(rg, signer, router); // +10 POL to CASRG pool
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
