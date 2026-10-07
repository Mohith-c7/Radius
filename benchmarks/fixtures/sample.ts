import { calculate_total } from './sample';

export class PaymentGateway {
    processPayment(amount: number): boolean {
        return amount > 0;
    }
}
