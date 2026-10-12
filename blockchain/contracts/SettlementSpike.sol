// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;

/// @notice Milestone 0 only: proves a signed gateway can record non-monetary credits.
contract SettlementSpike {
    struct Receipt {
        uint256 actor;
        uint256 nonceHash;
        uint256 creditUnits;
    }

    mapping(uint256 => Receipt) private receipts;

    function settle(
        uint256 intentHash,
        uint256 actor,
        uint256 nonceHash,
        uint256 creditUnits
    ) public returns (bool) {
        require(creditUnits > 0, "credit units required");
        require(receipts[intentHash].creditUnits == 0, "intent already settled");
        receipts[intentHash] = Receipt(actor, nonceHash, creditUnits);
        return true;
    }

    function creditUnitsFor(uint256 intentHash) public view returns (uint256) {
        return receipts[intentHash].creditUnits;
    }
}
