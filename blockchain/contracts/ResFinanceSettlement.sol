// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;

/// @notice Authoritative V1 group-obligation and non-redeemable credit ledger.
/// @dev This contract is reachable only through the private FastAPI signed-intent
/// gateway. Credit units are accounting entries with no redemption or monetary value.
contract ResFinanceSettlement {
    enum Status {
        NONE,
        PENDING,
        OPEN,
        PARTIALLY_SETTLED,
        SETTLED,
        REJECTED,
        CANCELLED
    }

    struct Obligation {
        uint256 creditor;
        uint256 debtor;
        uint256 amountMinorUnits;
        uint256 settledMinorUnits;
        Status status;
        uint256 creationIntentHash;
    }

    struct Receipt {
        uint256 operation;
        uint256 obligationId;
        uint256 amountMinorUnits;
        uint256 debtorCreditBalance;
        uint256 creditorCreditBalance;
    }

    uint256 private constant OP_CREATE = 1;
    uint256 private constant OP_APPROVE = 2;
    uint256 private constant OP_REJECT = 3;
    uint256 private constant OP_FUND = 4;
    uint256 private constant OP_SETTLE = 5;
    uint256 private constant OP_CANCEL = 6;

    mapping(uint256 => Obligation) private obligations;
    mapping(uint256 => uint256) private creditBalances;
    mapping(uint256 => Receipt) private receipts;
    mapping(uint256 => bool) private usedOperations;
    mapping(uint256 => bool) private usedIntentHashes;
    mapping(uint256 => bool) private usedNonceHashes;

    function createObligation(
        uint256 operationId,
        uint256 intentHash,
        uint256 nonceHash,
        uint256 creditor,
        uint256 debtor,
        uint256 amountMinorUnits
    ) public returns (bool) {
        require(!usedOperations[operationId], "operation replay");
        require(obligations[operationId].status == Status.NONE, "obligation exists");
        require(creditor != 0 && debtor != 0 && creditor != debtor, "invalid parties");
        require(amountMinorUnits > 0, "amount required");
        obligations[operationId] = Obligation(
            creditor,
            debtor,
            amountMinorUnits,
            0,
            Status.PENDING,
            intentHash
        );
        usedOperations[operationId] = true;
        receipts[operationId] = Receipt(OP_CREATE, operationId, amountMinorUnits, 0, 0);
        // One signed split may create several obligations, so its intent and nonce are
        // recorded on each obligation but are not globally consumed here.
        require(nonceHash != 0, "nonce required");
        return true;
    }

    function decideObligation(
        uint256 intentHash,
        uint256 nonceHash,
        uint256 obligationId,
        uint256 actor,
        uint256 decision
    ) public returns (bool) {
        _consume(intentHash, nonceHash);
        Obligation storage obligationValue = obligations[obligationId];
        require(obligationValue.status == Status.PENDING, "not pending");
        require(obligationValue.debtor == actor, "debtor required");
        require(decision == 1 || decision == 2, "invalid decision");
        obligationValue.status = decision == 1 ? Status.OPEN : Status.REJECTED;
        receipts[intentHash] = Receipt(
            decision == 1 ? OP_APPROVE : OP_REJECT,
            obligationId,
            obligationValue.amountMinorUnits,
            _creditBalance(obligationValue.debtor),
            _creditBalance(obligationValue.creditor)
        );
        return true;
    }

    function fundCredits(
        uint256 intentHash,
        uint256 nonceHash,
        uint256 actor,
        uint256 amountMinorUnits
    ) public returns (bool) {
        _consume(intentHash, nonceHash);
        require(actor != 0 && amountMinorUnits > 0, "invalid funding");
        uint256 fundedBalance = _creditBalance(actor) + amountMinorUnits;
        _setCreditBalance(actor, fundedBalance);
        receipts[intentHash] = Receipt(
            OP_FUND,
            0,
            amountMinorUnits,
            fundedBalance,
            0
        );
        return true;
    }

    function settleObligation(
        uint256 intentHash,
        uint256 nonceHash,
        uint256 obligationId,
        uint256 actor,
        uint256 amountMinorUnits
    ) public returns (bool) {
        _consume(intentHash, nonceHash);
        Obligation storage obligationValue = obligations[obligationId];
        require(
            obligationValue.status == Status.OPEN ||
                obligationValue.status == Status.PARTIALLY_SETTLED,
            "not open"
        );
        require(obligationValue.debtor == actor, "debtor required");
        require(amountMinorUnits > 0, "amount required");
        require(
            obligationValue.settledMinorUnits + amountMinorUnits <=
                obligationValue.amountMinorUnits,
            "overpayment"
        );
        uint256 debtorBalance = _creditBalance(actor);
        require(debtorBalance >= amountMinorUnits, "insufficient credits");

        debtorBalance -= amountMinorUnits;
        uint256 creditorBalance =
            _creditBalance(obligationValue.creditor) + amountMinorUnits;
        // The pinned ResContract persistence layer does not retain deleted EVM
        // storage slots across restart. Store logical balances plus one so a
        // logical zero remains an explicit, durable nonzero slot value.
        _setCreditBalance(actor, debtorBalance);
        _setCreditBalance(obligationValue.creditor, creditorBalance);
        obligationValue.settledMinorUnits += amountMinorUnits;
        obligationValue.status = obligationValue.settledMinorUnits ==
            obligationValue.amountMinorUnits
            ? Status.SETTLED
            : Status.PARTIALLY_SETTLED;
        receipts[intentHash] = Receipt(
            OP_SETTLE,
            obligationId,
            amountMinorUnits,
            debtorBalance,
            creditorBalance
        );
        return true;
    }

    function cancelObligation(
        uint256 intentHash,
        uint256 nonceHash,
        uint256 obligationId,
        uint256 actor
    ) public returns (bool) {
        _consume(intentHash, nonceHash);
        Obligation storage obligationValue = obligations[obligationId];
        require(obligationValue.status == Status.PENDING, "not pending");
        require(obligationValue.creditor == actor, "creditor required");
        obligationValue.status = Status.CANCELLED;
        receipts[intentHash] = Receipt(OP_CANCEL, obligationId, 0, 0, 0);
        return true;
    }

    function obligationCreditor(uint256 obligationId) public view returns (uint256) {
        return obligations[obligationId].creditor;
    }

    function obligationDebtor(uint256 obligationId) public view returns (uint256) {
        return obligations[obligationId].debtor;
    }

    function obligationAmount(uint256 obligationId) public view returns (uint256) {
        return obligations[obligationId].amountMinorUnits;
    }

    function obligationSettled(uint256 obligationId) public view returns (uint256) {
        return obligations[obligationId].settledMinorUnits;
    }

    function obligationStatus(uint256 obligationId) public view returns (uint256) {
        return uint256(obligations[obligationId].status);
    }

    function creditBalance(uint256 actor) public view returns (uint256) {
        return _creditBalance(actor);
    }

    function receiptOperation(uint256 intentHash) public view returns (uint256) {
        return receipts[intentHash].operation;
    }

    function receiptObligation(uint256 intentHash) public view returns (uint256) {
        return receipts[intentHash].obligationId;
    }

    function receiptAmount(uint256 intentHash) public view returns (uint256) {
        return receipts[intentHash].amountMinorUnits;
    }

    function receiptDebtorBalance(uint256 intentHash) public view returns (uint256) {
        return receipts[intentHash].debtorCreditBalance;
    }

    function receiptCreditorBalance(uint256 intentHash) public view returns (uint256) {
        return receipts[intentHash].creditorCreditBalance;
    }

    function _consume(uint256 intentHash, uint256 nonceHash) private {
        require(intentHash != 0 && nonceHash != 0, "intent required");
        require(!usedIntentHashes[intentHash], "intent replay");
        require(!usedNonceHashes[nonceHash], "nonce replay");
        usedIntentHashes[intentHash] = true;
        usedNonceHashes[nonceHash] = true;
    }

    function _creditBalance(uint256 actor) private view returns (uint256) {
        uint256 storedBalance = creditBalances[actor];
        return storedBalance == 0 ? 0 : storedBalance - 1;
    }

    function _setCreditBalance(uint256 actor, uint256 balance) private {
        creditBalances[actor] = balance + 1;
    }
}
