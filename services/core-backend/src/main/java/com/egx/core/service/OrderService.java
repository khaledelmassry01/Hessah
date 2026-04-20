package com.egx.core.service;

import com.egx.core.domain.AllocationExecution;
import com.egx.core.domain.TradeOrder;
import com.egx.core.domain.enums.OrderSide;
import com.egx.core.domain.enums.OrderStatus;
import com.egx.core.domain.enums.SettlementStatus;
import com.egx.core.repository.AllocationExecutionRepository;
import com.egx.core.repository.TradeOrderRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Service
public class OrderService {

    private final TradeOrderRepository tradeOrderRepository;
    private final AllocationExecutionRepository allocationExecutionRepository;

    public OrderService(
            TradeOrderRepository tradeOrderRepository,
            AllocationExecutionRepository allocationExecutionRepository
    ) {
        this.tradeOrderRepository = tradeOrderRepository;
        this.allocationExecutionRepository = allocationExecutionRepository;
    }

    @Transactional
    public List<TradeOrder> createPendingOrdersFromAllocations(
            Long userId,
            Long portfolioRunId,
            List<AllocationExecution> allocations
    ) {
        LocalDate tradeDate = LocalDate.now();
        LocalDate settlementDate = addBusinessDays(tradeDate, 2);

        List<TradeOrder> orders = new ArrayList<>();
        for (AllocationExecution allocation : allocations) {
            allocation.setSettlementStatus(SettlementStatus.PENDING);
            allocation.setSettlementDate(settlementDate);

            if (allocation.getExecutedShares() == null || allocation.getExecutedShares() <= 0) {
                continue;
            }

            TradeOrder order = new TradeOrder();
            order.setUserId(userId);
            order.setPortfolioRunId(portfolioRunId);
            order.setStockId(allocation.getStockId());
            order.setSide(OrderSide.BUY);
            order.setOrderQty(allocation.getExecutedShares());
            order.setFilledQty(allocation.getExecutedShares());
            order.setAvgFillPrice(allocation.getPriceSnapshot());
            order.setOrderStatus(OrderStatus.FILLED);
            order.setTradeDate(tradeDate);
            order.setSettlementDate(settlementDate);
            order.setSettlementStatus(SettlementStatus.PENDING);
            order.setCreatedAt(LocalDateTime.now());
            orders.add(order);
        }

        allocationExecutionRepository.saveAll(allocations);
        return tradeOrderRepository.saveAll(orders);
    }

    public LocalDate addBusinessDays(LocalDate from, int businessDays) {
        LocalDate cursor = from;
        int added = 0;

        while (added < businessDays) {
            cursor = cursor.plusDays(1);
            switch (cursor.getDayOfWeek()) {
                case FRIDAY, SATURDAY -> {
                }
                default -> added++;
            }
        }

        return cursor;
    }
}
