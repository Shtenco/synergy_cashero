const fs = require("fs");
require("dotenv").config();
const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const router = process.env.ROUTER_V2 || "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
  const founderVesting = process.env.FOUNDER_VESTING;
  const projectVault = process.env.PROJECT_VAULT;

  if (!founderVesting || !projectVault) {
    throw new Error("Set FOUNDER_VESTING and PROJECT_VAULT in .env");
  }

  console.log("Deployer:", deployer.address);
  console.log("Router:", router);

  const RS = await hre.ethers.getContractFactory("CASRSv3");
  const rs = await RS.deploy(router, founderVesting, projectVault);
  await rs.waitForDeployment();
  const rsAddr = await rs.getAddress();
  console.log("CASRSv3 deployed:", rsAddr);

  const RG = await hre.ethers.getContractFactory("CASRGv3");
  const rg = await RG.deploy(rsAddr);
  await rg.waitForDeployment();
  const rgAddr = await rg.getAddress();
  console.log("CASRGv3 deployed:", rgAddr);

  // set bot role to deployer by default (change later if needed)
  const tx1 = await rs.setBot(deployer.address);
  await tx1.wait();
  const tx2 = await rg.setBot(deployer.address);
  await tx2.wait();
  console.log("Bot role set to deployer");

  const out = {
    network: hre.network.name,
    deployer: deployer.address,
    router,
    CASRSv3: rsAddr,
    CASRGv3: rgAddr,
    founderVesting,
    projectVault,
    ts: new Date().toISOString(),
  };

  fs.writeFileSync("v3-deploy-addresses.json", JSON.stringify(out, null, 2));
  console.log("Saved v3-deploy-addresses.json");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
