require("dotenv").config();
require("@nomicfoundation/hardhat-ethers");

const { OWNER_PRIVATE_KEY, RPC_POLYGON, RPC_AMOY } = process.env;

module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 },
      viaIR: true,
    },
  },
  paths: {
    sources: "./contracts",
    cache: "./cache",
    artifacts: "./artifacts"
  },
  networks: {
    polygon: {
      url: RPC_POLYGON || "https://polygon-rpc.com",
      chainId: 137,
      accounts: OWNER_PRIVATE_KEY ? [OWNER_PRIVATE_KEY] : [],
    },
    amoy: {
      url: RPC_AMOY || "https://rpc-amoy.polygon.technology/",
      chainId: 80002,
      accounts: OWNER_PRIVATE_KEY ? [OWNER_PRIVATE_KEY] : [],
    },
    hardhat: {},
  },
};
