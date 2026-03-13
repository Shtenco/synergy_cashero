const { Wallet } = require("ethers");
const fs = require("fs");

fs.mkdirSync("wallets", { recursive: true });
for (let i = 0; i < 25; i++) {
  const w = Wallet.createRandom();
  const name = i === 0 ? "owner" : `bot${i}`;
  fs.writeFileSync(
    `wallets/${name}.env`,
    `PRIVATE_KEY=${w.privateKey}\nADDRESS=${w.address}\n`
  );
}
console.log("generated 25 wallets");
