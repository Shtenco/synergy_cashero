require("dotenv").config();
require("@nomicfoundation/hardhat-ethers");

const { OWNER_PRIVATE_KEY, RPC_POLYGON, RPC_MUMBAI, RPC_AMOY } = process.env;

module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 },
      viaIR: true,
    },
  },
  networks: {
    polygon: {
      url: RPC_POLYGON || "https://polygon-rpc.com",
      accounts: OWNER_PRIVATE_KEY ? [OWNER_PRIVATE_KEY] : []
    },
    mumbai: {
      url: RPC_MUMBAI || "https://rpc-mumbai.maticvigil.com",
      accounts: OWNER_PRIVATE_KEY ? [OWNER_PRIVATE_KEY] : []
    },
    amoy: {
      url: RPC_AMOY || "https://rpc-amoy.polygon.technology/",
      chainId: 80002,
      accounts: OWNER_PRIVATE_KEY ? [OWNER_PRIVATE_KEY] : []
    },
    hardhat: {}
  }
};
